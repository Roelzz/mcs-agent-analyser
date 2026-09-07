"""Local, deterministic static audit of the instruction assets in a bot export.

Thin adapter over `rule-audit` (https://github.com/hermes-labs-ai/rule-audit) —
the same analyzer the repo already runs as a pre-commit hook on `prompts/*.md`,
here pointed at the *analysed bot's* own instructions instead of ours.

No detection logic lives in this module. Severity, risk labels and the
pass/warn/fail mapping all come from rule-audit's published contract:

    LOW -> pass, MEDIUM -> warn, HIGH/CRITICAL -> fail (the CLI's exit-2 case)

which is `rule_audit.evidence.RISK_SEVERITY` verbatim.

Scope is deliberately *instruction text* — the main agent system prompt,
connected-agent instructions, and inline `SearchAndSummarizeContent`
prompts. Tool/topic `description` and `modelDescription` fields are agent
*config* rather than instruction prose, and rule-audit is explicit that
config/tool-description linting is a different tool's job.

Everything here is offline: rule-audit is pure stdlib and makes no network
calls, so this does not move the "your data stays yours" boundary.

Disable with `MCS_DISABLE_INSTRUCTION_AUDIT=1`; uninstall by dropping the
`rule-audit` dependency (the section then degrades to a one-line note).
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from config import settings
from models import BotProfile

try:  # pragma: no cover - exercised by test_missing_dependency_degrades
    from rule_audit import __version__ as RULE_AUDIT_VERSION, audit
    from rule_audit.evidence import RISK_SEVERITY

    RULE_AUDIT_AVAILABLE = True
except ImportError:  # pragma: no cover - only when the optional dep is removed
    RULE_AUDIT_VERSION = ""
    RULE_AUDIT_AVAILABLE = False

#: Per-asset input cap. rule-audit's contradiction pass is O(rules^2), and
#: findings grow quadratically *within* the cap, so this bounds output as
#: well as time. Real system prompts sit in the low thousands of characters
#: (the largest fixture is 6.5k -> ~6ms); a dense 8k asset costs ~130ms.
MAX_AUDIT_CHARS = 8_000

#: Per-report cap on total audited characters. `render_report` is called
#: synchronously from the Reflex upload handler, so an export with many large
#: `additionalInstructions` blocks would otherwise stall every connected user.
#: Assets past the budget are listed as `unknown`, never silently dropped.
MAX_TOTAL_AUDIT_CHARS = 32_000

#: Status shown when nothing could be checked. Distinct from "pass" on
#: purpose: rule-audit emits `input.no-rules-parsed` precisely because a
#: prompt it could not parse says *nothing* about the prompt's content.
UNKNOWN = "unknown"


class InstructionAsset(BaseModel):
    """One block of instruction prose harvested from `botContent.yml`."""

    kind: str  # "agent" | "connected_agent" | "inline_prompt"
    label: str
    source: str  # where in the export it came from, for the report
    text: str


class AssetAudit(BaseModel):
    """rule-audit's verdict on one asset, plus where that asset is used.

    `status`, `risk_label` and `risk_score` are rule-audit's own outputs.
    Only `status` is nuanced by this module, and only in the direction of
    *less* confidence — see `_status_for`.
    """

    label: str
    source: str
    kind: str
    chars: int
    status: str
    risk_label: str = ""
    risk_score: float = 0.0
    rule_count: int = 0
    contradictions: list[dict] = Field(default_factory=list)
    priority_ambiguities: list[dict] = Field(default_factory=list)
    meta_paradoxes: list[dict] = Field(default_factory=list)
    absoluteness_issues: list[dict] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    note: str = ""
    #: Other assets with byte-identical text, audited once and reported here.
    also_used_by: list[str] = Field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        """Findings that point at specific rules — i.e. everything but the
        coverage gaps, which are absence-of-topic heuristics."""
        return (
            len(self.contradictions)
            + len(self.priority_ambiguities)
            + len(self.meta_paradoxes)
            + len(self.absoluteness_issues)
        )


class InstructionAuditReport(BaseModel):
    """All asset verdicts for one bot, plus why the run may be empty."""

    available: bool = True
    enabled: bool = True
    tool_version: str = ""
    assets: list[AssetAudit] = Field(default_factory=list)
    unavailable_reason: str = ""

    @property
    def ran(self) -> bool:
        return self.available and self.enabled

    @property
    def high_severity_contradictions(self) -> int:
        return sum(sum(1 for c in a.contradictions if c.get("severity") == "high") for a in self.assets)

    @property
    def exit_code(self) -> int:
        """rule-audit's CLI exit-code contract, restated over every asset:
        2 when any audited asset is HIGH/CRITICAL, else 0."""
        return 2 if any(a.status == "fail" for a in self.assets) else 0


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_instruction_assets(profile: BotProfile) -> list[InstructionAsset]:
    """Harvest every instruction-prose asset the parser already extracted.

    Ordered most- to least-load-bearing: the agent's own system prompt first,
    then connected-agent instructions, then inline topic prompts.
    """
    assets: list[InstructionAsset] = []

    gpt = profile.gpt_info
    if gpt and gpt.instructions and gpt.instructions.strip():
        assets.append(
            InstructionAsset(
                kind="agent",
                label=f"{profile.display_name} — system instructions",
                source="`gptComponentMetadata.instructions`",
                text=gpt.instructions,
            )
        )

    for component in profile.components:
        if component.agent_instructions and component.agent_instructions.strip():
            assets.append(
                InstructionAsset(
                    kind="connected_agent",
                    label=f"{component.display_name} — agent instructions",
                    source=f"`{component.schema_name}` → `settings.instructions`",
                    text=component.agent_instructions,
                )
            )

    for prompt in profile.inline_prompts:
        if not prompt.text or not prompt.text.strip():
            continue
        assets.append(
            InstructionAsset(
                kind="inline_prompt",
                label=f"{prompt.host_topic_display} — {prompt.kind}",
                source=f"`{prompt.host_topic_schema}` → `additionalInstructions`",
                text=prompt.text,
            )
        )

    return assets


def _status_for(risk_label: str, rule_count: int) -> str:
    """rule-audit's risk -> status map, with one honest exception.

    When rule-audit parses no rules, the risk score is exactly
    `len(gaps) * 5` against an *empty* rule set, so `RISK_SEVERITY` alone
    lands anywhere from LOW (a false clearance) to HIGH (a false
    accusation) depending only on how many domains the text failed to
    mention. rule-audit flags that case itself — `input.no-rules-parsed`,
    severity `unknown` — so we surface it as `unknown` rather than letting
    either misreading through. Nothing was checked; that is neither a pass
    nor a finding.
    """
    if rule_count == 0:
        return UNKNOWN
    return RISK_SEVERITY.get(risk_label, "warn")


_NOT_CHECKED = "Nothing was checked, so this says nothing about the prompt's content."


def _skipped(asset: InstructionAsset, note: str) -> AssetAudit:
    return AssetAudit(
        label=asset.label,
        source=asset.source,
        kind=asset.kind,
        chars=len(asset.text),
        status=UNKNOWN,
        note=note,
    )


def _skip_reason(asset: InstructionAsset, budget_left: int) -> str:
    """Why this asset must not be scanned, or "" if it may be."""
    if len(asset.text) > MAX_AUDIT_CHARS:
        return (
            f"Not audited — {len(asset.text):,} characters exceeds the "
            f"{MAX_AUDIT_CHARS:,}-character per-asset cap. {_NOT_CHECKED}"
        )
    if len(asset.text) > budget_left:
        return (
            f"Not audited — this report's {MAX_TOTAL_AUDIT_CHARS:,}-character "
            f"analysis budget was already spent on earlier assets. {_NOT_CHECKED}"
        )
    return ""


def _audit_text(asset: InstructionAsset) -> AssetAudit:
    """Run rule-audit over one asset. Reads and writes nothing; no network."""
    report = audit(asset.text)
    # `to_dict()` also carries `generated_at`; it is deliberately not read,
    # so two runs over the same export render byte-identical output.
    # `.get()` throughout: an unforeseen rule-audit release must degrade the
    # section, not crash every report render.
    data = report.to_dict()
    rule_count = data.get("rule_count", 0)
    risk_label = data.get("risk_label", "")

    return AssetAudit(
        label=asset.label,
        source=asset.source,
        kind=asset.kind,
        chars=len(asset.text),
        status=_status_for(risk_label, rule_count),
        risk_label=risk_label,
        risk_score=data.get("risk_score", 0.0),
        rule_count=rule_count,
        contradictions=data.get("contradictions", []),
        priority_ambiguities=data.get("priority_ambiguities", []),
        meta_paradoxes=data.get("meta_paradoxes", []),
        absoluteness_issues=data.get("absoluteness_issues", []),
        gaps=data.get("gaps", []),
        note=(
            "rule-audit parsed no rules from this text, so nothing was checked. "
            "The coverage gaps below are reported against an empty rule set."
            if rule_count == 0
            else ""
        ),
    )


def audit_instructions(profile: BotProfile) -> InstructionAuditReport:
    """Audit every instruction asset on `profile`, each unique text once."""
    if getattr(settings, "mcs_disable_instruction_audit", False):
        return InstructionAuditReport(
            enabled=False,
            unavailable_reason="Disabled via MCS_DISABLE_INSTRUCTION_AUDIT.",
        )

    if not RULE_AUDIT_AVAILABLE:
        return InstructionAuditReport(
            available=False,
            unavailable_reason=(
                "`rule-audit` is not installed. Run `pip install rule-audit` "
                "(or add it back to `pyproject.toml` and run `uv lock && uv sync`) "
                "to enable this section."
            ),
        )

    results: list[AssetAudit] = []
    seen: dict[str, AssetAudit] = {}
    budget_left = MAX_TOTAL_AUDIT_CHARS

    for asset in collect_instruction_assets(profile):
        key = _digest(asset.text)
        previous = seen.get(key)
        if previous is not None:
            # Byte-identical prompt — e.g. the same conversational-boosting
            # block on several topics. Scan once, cross-reference the rest.
            previous.also_used_by.append(asset.label)
            continue
        reason = _skip_reason(asset, budget_left)
        if reason:
            result = _skipped(asset, reason)
        else:
            result = _audit_text(asset)
            budget_left -= len(asset.text)
        seen[key] = result
        results.append(result)

    return InstructionAuditReport(tool_version=RULE_AUDIT_VERSION, assets=results)


__all__ = [
    "MAX_AUDIT_CHARS",
    "MAX_TOTAL_AUDIT_CHARS",
    "RULE_AUDIT_AVAILABLE",
    "AssetAudit",
    "InstructionAsset",
    "InstructionAuditReport",
    "audit_instructions",
    "collect_instruction_assets",
]
