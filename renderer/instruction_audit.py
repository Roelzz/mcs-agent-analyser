"""Renders the `## Instruction Audit (static)` report section.

Presentation only — every severity, span and description below is copied
from what `rule-audit` produced in `instruction_audit.py`. Nothing here
re-derives a verdict.

Findings are split into two blocks on purpose. Contradictions, priority
ambiguities, meta-paradoxes and absoluteness challenges each point at
specific rules in the prompt and carry character spans. Coverage gaps say a
*topic is absent*, which is advisory: they fire on any short prompt and are
the main driver of rule-audit's composite risk score, so presenting them
alongside evidence-bearing findings would overstate both.
"""

from instruction_audit import MAX_AUDIT_CHARS, MAX_TOTAL_AUDIT_CHARS, AssetAudit, audit_instructions
from models import BotProfile

from ._helpers import _sanitize_table_cell

#: Findings per family, per asset. rule-audit's contradiction pass is
#: O(rules^2), so a dense prompt can legitimately produce tens of thousands
#: of pairs. The report is read by a human and shipped over a websocket;
#: truncating loudly beats emitting megabytes nobody scrolls through.
MAX_ROWS_PER_FAMILY = 50

_STATUS_BADGE = {
    "pass": "\U0001f7e2",  # green circle
    "warn": "\U0001f7e1",  # yellow circle
    "fail": "\U0001f534",  # red circle
    "unknown": "⚪",  # white circle
}

_SEVERITY_BADGE = {"high": "\U0001f534", "medium": "\U0001f7e1", "low": "\U0001f535"}

_INTRO = (
    "Offline logical analysis of the instruction text in this export, by"
    " [rule-audit](https://github.com/hermes-labs-ai/rule-audit) — the same static analyzer"
    " this repo runs as a pre-commit hook, pointed at the analysed agent's own prompts."
    " It looks for rules that contradict each other, priority conflicts with no tie-breaker,"
    " self-referential instructions, and absolute rules with obvious exceptions.\n"
)

_BOUNDARY = (
    "> Runs locally on your machine. No API key, no network call, no data leaves the box —"
    " this is not part of the opt-in LLM enrichment.\n"
)

_CAVEAT = (
    "> **Reading this section.** Findings are lexical, not semantic: rule-audit reasons about"
    " modality (`must` / `must not` / `may`) and shared keywords, so it will miss contradictions"
    " phrased indirectly and can flag pairs a human would reconcile from context. Treat each row"
    " as a prompt to re-read those two rules, not as a defect."
    " `unknown` means nothing was checked — it is not a pass.\n"
)


def _text(value: object) -> str:
    """Neutralise a value derived from the uploaded bot's own prompt text.

    `_sanitize_table_cell` handles pipes and newlines; this also defuses the
    HTML and Markdown that would otherwise be interpreted. The exports run
    the report through `marked.parse` into `innerHTML` with no sanitizer
    (`web/mermaid.py`), so a prompt containing `<img onerror=...>` or a
    stray `</details>` must not survive as live markup. Square brackets are
    escaped too, so `[x](javascript:...)` cannot become a clickable link —
    and backslashes first, so an input `\\[` cannot cancel that escape.
    Never place the result inside a code span, where escapes do not apply.
    """
    text = _sanitize_table_cell(str(value)).replace("\\", "\\\\")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")


def _code(value: object) -> str:
    """Render untrusted text as an inline code span.

    Code-span content is literal in CommonMark and `marked` — no Markdown,
    and HTML is escaped — so the only ways out are a backtick closing the
    span early or a blank line ending the paragraph. Both are removed rather
    than escaped, because backslash escapes do not apply inside a code span.
    """
    return "`" + _sanitize_table_cell(str(value)).replace("`", "'") + "`"


def _fence(body: str) -> list[str]:
    """Wrap untrusted multi-line text in a code fence long enough to hold it.

    Matches how every other `<details>` body in the renderer is emitted
    (see `renderer/knowledge.py`, `renderer/tools.py`).
    """
    longest = 0
    run = 0
    for char in body:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    marker = "`" * max(3, longest + 1)
    return [marker, body, marker]


def _more(shown: int, total: int, noun: str) -> list[str]:
    if total <= shown:
        return []
    return [f"_…and {total - shown:,} more {noun} not shown._\n"]


def _span(item: dict, key: str) -> str:
    span = item.get(key) or {}
    start, end = span.get("start"), span.get("end")
    if start is None or end is None:
        return "—"
    return f"{start}–{end}"


def _headline(asset: AssetAudit) -> str:
    """One line saying what was actually found, in evidence terms."""
    if asset.status == "unknown":
        return "nothing checked"
    bits: list[str] = []
    if asset.contradictions:
        high = sum(1 for c in asset.contradictions if c.get("severity") == "high")
        text = f"{len(asset.contradictions)} contradiction{'s' if len(asset.contradictions) != 1 else ''}"
        if high:
            text += f" ({high} high)"
        bits.append(text)
    if asset.priority_ambiguities:
        bits.append(
            f"{len(asset.priority_ambiguities)} priority conflict{'s' if len(asset.priority_ambiguities) != 1 else ''}"
        )
    if asset.meta_paradoxes:
        bits.append(f"{len(asset.meta_paradoxes)} meta-paradox{'es' if len(asset.meta_paradoxes) != 1 else ''}")
    if asset.absoluteness_issues:
        bits.append(
            f"{len(asset.absoluteness_issues)} absolute rule{'s' if len(asset.absoluteness_issues) != 1 else ''} with exceptions"
        )
    if not bits:
        return "no rule-level findings"
    return ", ".join(bits)


def _render_asset(asset: AssetAudit) -> list[str]:
    lines: list[str] = [f"### {_text(asset.label)}\n"]

    # `source` embeds schema names from the uploaded export — never raw.
    meta = [f"Source: {_code(asset.source)}", f"{asset.chars:,} chars"]
    if asset.rule_count:
        meta.append(f"{asset.rule_count} rules parsed")
    if not asset.uses_composite_risk:
        meta.append("scored on rule-level findings only — system-prompt risk score and coverage gaps do not apply")
    elif asset.risk_label:
        meta.append(f"rule-audit risk: **{asset.risk_label}** ({asset.risk_score:.0f}/100)")
    lines.append(" · ".join(meta) + "\n")

    if asset.also_used_by:
        shared = ", ".join(_text(label) for label in asset.also_used_by)
        lines.append(f"_Identical text also used by: {shared}. Audited once._\n")

    if asset.note:
        lines.append(f"> {_text(asset.note)}\n")

    if asset.contradictions:
        lines.append("**Contradictions**\n")
        lines.append("| Severity | Type | Rules | Spans | Finding |")
        lines.append("| --- | --- | --- | --- | --- |")
        shown = asset.contradictions[:MAX_ROWS_PER_FAMILY]
        for c in shown:
            badge = _SEVERITY_BADGE.get(c.get("severity", ""), "⚪")
            rules = f"[{c.get('rule_a_index')}] ↔ [{c.get('rule_b_index')}]"
            spans = f"{_span(c, 'rule_a_span')}, {_span(c, 'rule_b_span')}"
            lines.append(
                f"| {badge} {_text(c.get('severity', '—'))}"
                f" | {_text(c.get('conflict_type', '—'))}"
                f" | {rules} | {spans}"
                f" | {_text(c.get('description', ''))} |"
            )
        lines.append("")
        lines.extend(_more(len(shown), len(asset.contradictions), "contradictions"))
        lines.append("<details><summary>Conflicting rule text</summary>\n")
        body: list[str] = []
        for c in shown:
            body.append(f"[{c.get('rule_a_index')}] {_sanitize_table_cell(c.get('rule_a_text', ''))}")
            body.append(f"[{c.get('rule_b_index')}] {_sanitize_table_cell(c.get('rule_b_text', ''))}")
            body.append("")
        lines.extend(_fence("\n".join(body).rstrip()))
        lines.append("\n</details>\n")

    if asset.priority_ambiguities:
        lines.append("**Priority conflicts** — both rules fire, nothing says which wins.\n")
        shown = asset.priority_ambiguities[:MAX_ROWS_PER_FAMILY]
        for p in shown:
            lines.append(f"- {_text(p.get('description', ''))}")
            scenario = p.get("scenario")
            if scenario:
                lines.append(f"  - _{_text(scenario)}_")
        lines.append("")
        lines.extend(_more(len(shown), len(asset.priority_ambiguities), "priority conflicts"))

    if asset.meta_paradoxes:
        lines.append("**Meta-paradoxes** — instructions that talk about themselves.\n")
        shown = asset.meta_paradoxes[:MAX_ROWS_PER_FAMILY]
        for m in shown:
            lines.append(
                f"- `[{m.get('rule_index')}]` ({_text(m.get('paradox_type', '—'))}) {_text(m.get('description', ''))}"
            )
        lines.append("")
        lines.extend(_more(len(shown), len(asset.meta_paradoxes), "meta-paradoxes"))

    if asset.absoluteness_issues:
        lines.append("**Absolute rules with a plausible exception**\n")
        shown = asset.absoluteness_issues[:MAX_ROWS_PER_FAMILY]
        for a in shown:
            lines.append(
                f"- `[{a.get('rule_index')}]` ({_text(a.get('challenge_type', '—'))}) {_text(a.get('challenge', ''))}"
            )
        lines.append("")
        lines.extend(_more(len(shown), len(asset.absoluteness_issues), "absoluteness challenges"))

    gaps = asset.gaps if asset.uses_composite_risk else []
    if gaps:
        lines.append(
            f"<details><summary>Coverage gaps — {len(gaps)} topic"
            f"{'s' if len(gaps) != 1 else ''} the prompt never addresses (advisory)</summary>\n"
        )
        for g in gaps[:MAX_ROWS_PER_FAMILY]:
            lines.append(f"- **{_text(g.get('gap_type', '—'))}** — {_text(g.get('description', ''))}")
            example = g.get("example_scenario")
            if example:
                lines.append(f"  - _{_text(example)}_")
        lines.append("\n</details>\n")

    if asset.status != "unknown" and not asset.evidence_count and not gaps:
        lines.append("_No findings._\n")

    return lines


def render_instruction_audit_section(profile: BotProfile) -> str:
    """Render `## Instruction Audit (static)`. Always returns a section when
    the bot has instruction text, so a clean result is visibly clean rather
    than indistinguishable from a section that silently did not run."""
    report = audit_instructions(profile)

    if not report.ran:
        return "\n".join(
            [
                "## Instruction Audit (static)\n",
                _INTRO,
                f"> Not run. {report.unavailable_reason}\n",
            ]
        )

    if not report.assets:
        return ""

    lines: list[str] = ["## Instruction Audit (static)\n", _INTRO, _BOUNDARY]

    lines.append("| Instruction asset | Status | Findings |")
    lines.append("| --- | --- | --- |")
    for asset in report.assets:
        badge = _STATUS_BADGE.get(asset.status, "⚪")
        lines.append(f"| {_text(asset.label)} | {badge} {asset.status} | {_text(_headline(asset))} |")
    lines.append("")

    if report.exit_code == 2:
        failing = sum(1 for a in report.assets if a.status == "fail")
        high = report.high_severity_contradictions
        headline = (
            f"**{high} high-severity contradiction{'s' if high != 1 else ''}**"
            if high
            else f"**{failing} instruction asset{'s' if failing != 1 else ''} at HIGH or CRITICAL risk**"
        )
        lines.append(
            f"{headline} across {len(report.assets)} instruction"
            f" asset{'s' if len(report.assets) != 1 else ''}."
            " `rule-audit` would exit `2` on this bot.\n"
        )

    lines.append(_CAVEAT)

    for asset in report.assets:
        lines.extend(_render_asset(asset))

    lines.append(
        f"_Analysed by rule-audit {report.tool_version}. Assets over {MAX_AUDIT_CHARS:,} characters,"
        f" and any beyond this report's {MAX_TOTAL_AUDIT_CHARS:,}-character budget, are listed but not"
        f" analysed; at most {MAX_ROWS_PER_FAMILY} findings per kind are shown per asset."
        " Disable this section with `MCS_DISABLE_INSTRUCTION_AUDIT=1`._\n"
    )

    return "\n".join(lines)
