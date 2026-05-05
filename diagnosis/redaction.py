"""PII redaction.

Stage 1 (always-on): regex-based replacement with typed placeholders. Patterns
chosen for the NL/EU customer base — emails, phones, IBAN, BSN (NL national
ID), credit card (Luhn-validated), and basic name patterns ("Mr/Mrs/Dhr/Mw +
Capitalised Word"). Outputs a `redaction_summary` so users can see what left
their environment.

Stage 2 (Phase 1.1, optional): LLM PII pass. Stub interface here — the
orchestrator calls `redact_text(text, llm_stage=False)` for now and the LLM
hook is a TODO.

Constraint checks run on the original timeline; redaction only applies to
text that is about to be shipped to an external LLM (judge, AI-rec generator).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RedactedText:
    text: str
    summary: dict[str, int]


# Order matters — longest / most-specific patterns first so they don't get
# eaten by shorter generic ones.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.IGNORECASE)),
    # IBAN: country code (2) + check (2) + BBAN (11-30 alphanumerics, may be
    # space-separated for display).
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", re.IGNORECASE)),
    # Credit card (Luhn-checked separately below). Must run BEFORE phone or
    # the phone pattern eats 13-19 digit card sequences with spaces.
    ("CARD_RAW", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    # Phone: international or 10-digit local; allow spaces, dashes, parens.
    ("PHONE", re.compile(r"\+?\d[\d\s\-().]{8,18}\d")),
    # BSN: 9-digit Dutch national ID — runs after phone so spaced phones
    # don't have 9-digit subsequences mistakenly matched.
    ("BSN", re.compile(r"\b\d{9}\b")),
    # Driving licence (NL): 10 digits.
    ("LICENCE", re.compile(r"\b\d{10}\b")),
    # Names with honorific.
    ("NAME", re.compile(r"\b(?:Mr|Mrs|Ms|Dhr|Mevr|Mw|Mr\.|Dhr\.|Mevr\.)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b")),
]


def _luhn_ok(digits: str) -> bool:
    s = [int(c) for c in re.sub(r"\D", "", digits)]
    if not 13 <= len(s) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(s)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact_text(text: str, *, llm_stage: bool = False) -> RedactedText:
    """Redact PII in `text`. Returns the new text and a summary dict.

    `llm_stage` is reserved for Phase 1.1; currently a no-op.
    """
    if not text:
        return RedactedText(text="", summary={})

    summary: dict[str, int] = {}
    out = text
    counters: dict[str, int] = {}

    for label, pat in _PATTERNS:

        def _replace(m: re.Match[str], _label: str = label) -> str:
            raw = m.group(0)
            if _label == "CARD_RAW" and not _luhn_ok(raw):
                return raw  # not a real card number, leave alone
            cat = "CARD" if _label == "CARD_RAW" else _label
            counters[cat] = counters.get(cat, 0) + 1
            summary[cat] = summary.get(cat, 0) + 1
            return f"[{cat}_{counters[cat]}]"

        out = pat.sub(_replace, out)

    # Phase 1.1 stub — when llm_stage=True, route `out` through a small-model
    # PII pass. Today it's a passthrough so the call site is stable.
    if llm_stage:
        pass

    return RedactedText(text=out, summary=summary)


def redact_dict(payload: dict, *, llm_stage: bool = False) -> tuple[dict, dict[str, int]]:
    """Redact every string value in a (shallow) dict. Used to scrub payloads
    before they're serialised for an LLM call. Returns (new_payload, summary)."""
    summary: dict[str, int] = {}
    new: dict = {}
    for k, v in payload.items():
        if isinstance(v, str):
            r = redact_text(v, llm_stage=llm_stage)
            new[k] = r.text
            for cat, count in r.summary.items():
                summary[cat] = summary.get(cat, 0) + count
        elif isinstance(v, list):
            new_list = []
            for item in v:
                if isinstance(item, str):
                    r = redact_text(item, llm_stage=llm_stage)
                    new_list.append(r.text)
                    for cat, count in r.summary.items():
                        summary[cat] = summary.get(cat, 0) + count
                else:
                    new_list.append(item)
            new[k] = new_list
        else:
            new[k] = v
    return new, summary
