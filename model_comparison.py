"""Multi-model comparison capability for Copilot Studio agents.

Provides:
- A model catalogue describing Copilot Studio-compatible models.
- ``build_comparison_markdown`` to produce a Markdown "Model Performance Comparison"
  section for an agent report.
- An optional API-backed comparison controlled by the ``MCS_ENABLE_MODEL_COMPARISON``
  environment variable (requires ``OPENAI_API_KEY`` to be set as well).

When ``MCS_ENABLE_MODEL_COMPARISON`` is not set or is falsy the feature gracefully
skips the live test and only reports the configured model plus static guidance.
"""

from __future__ import annotations

import json
import os

import httpx

from models import BotProfile

# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------

_MODEL_CATALOGUE: dict[str, dict] = {
    "gpt41": {
        "display": "GPT-4.1",
        "tier": "Flagship",
        "context_window": "1 M tokens",
        "cost_tier": "Standard",
        "strengths": [
            "Precise, complex instruction following",
            "Excellent for multi-step reasoning and tool use",
            "1 M-token context — ideal for large knowledge bases",
            "Strong persona adherence",
        ],
        "limitations": [
            "Higher cost than Mini/Nano variants",
            "May be slower than compact variants for simple queries",
        ],
        "recommendation": (
            "Good default choice for most enterprise agents. "
            "If cost is a concern, evaluate GPT-4.1 Mini for comparable accuracy at lower cost."
        ),
    },
    "gpt41mini": {
        "display": "GPT-4.1 Mini",
        "tier": "Standard",
        "context_window": "1 M tokens",
        "cost_tier": "Low",
        "strengths": [
            "Strong balance of quality and cost",
            "Faster response times than GPT-4.1",
            "Suitable for well-scoped, focused agents",
        ],
        "limitations": [
            "Less precise on very complex, multi-layered instructions than GPT-4.1",
            "May require shorter, more explicit instructions",
        ],
        "recommendation": (
            "Consider GPT-4.1 if the agent handles complex queries or nuanced instructions. "
            "GPT-4.1 Mini is a cost-effective choice for agents with clear, well-defined scope."
        ),
    },
    "gpt41nano": {
        "display": "GPT-4.1 Nano",
        "tier": "Compact",
        "context_window": "1 M tokens",
        "cost_tier": "Very Low",
        "strengths": [
            "Lowest cost in the GPT-4.1 family",
            "Fastest response times",
            "Suitable for simple FAQ or routing agents",
        ],
        "limitations": [
            "Less capable for nuanced or multi-step tasks",
            "Requires concise, simple instructions (< 1 500 chars recommended)",
            "May miss subtle context or implicit intent",
        ],
        "recommendation": (
            "Upgrade to GPT-4.1 Mini or GPT-4.1 if answer quality is insufficient. "
            "GPT-4.1 Nano is best for high-volume, low-complexity use cases."
        ),
    },
    "gpt5": {
        "display": "GPT-5",
        "tier": "Frontier",
        "context_window": "200 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Most capable model in the Copilot Studio catalogue",
            "Exceptional complex reasoning and synthesis",
            "Best-in-class instruction adherence and accuracy",
            "Suitable for research, legal, financial, or compliance agents",
        ],
        "limitations": [
            "Highest cost — validate ROI before deploying at scale",
            "Very long system instructions benefit from careful structuring",
        ],
        "recommendation": (
            "Using the most capable available model. "
            "Ensure cost aligns with business expectations; "
            "consider GPT-4.1 for lower-complexity topics."
        ),
    },
    "gpt5chat": {
        "display": "GPT-5 Chat",
        "tier": "Frontier / Conversational",
        "context_window": "128 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Optimised for conversational agents and dialogue flow",
            "High-quality, natural responses",
            "Strong grounding and factuality in conversational contexts",
        ],
        "limitations": [
            "Premium cost tier",
            "Slightly narrower context than GPT-5 base model",
        ],
        "recommendation": (
            "Using a premium conversational model. Evaluate whether GPT-4.1 meets quality requirements at lower cost."
        ),
    },
    "o1": {
        "display": "o1",
        "tier": "Reasoning",
        "context_window": "128 K tokens",
        "cost_tier": "High",
        "strengths": [
            "Step-by-step deliberate reasoning",
            "Excellent for math, coding, logic, and analytical tasks",
            "Reduced hallucination on structured problem-solving",
        ],
        "limitations": [
            "Slower responses due to reasoning process",
            "Not optimised for conversational / FAQ agents",
            "Higher latency may affect user experience",
        ],
        "recommendation": (
            "o1 is ideal for agents that solve structured problems (e.g., data analysis, code review). "
            "For conversational or FAQ agents, GPT-4.1 typically provides better latency and cost."
        ),
    },
    "o3": {
        "display": "o3",
        "tier": "Reasoning (Advanced)",
        "context_window": "200 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Most advanced reasoning capabilities",
            "Excellent for scientific, legal, or highly analytical tasks",
            "Broader context window than o1",
        ],
        "limitations": [
            "Premium cost and higher latency",
            "Overkill for general-purpose FAQ or customer service agents",
        ],
        "recommendation": (
            "Reserve for agents requiring expert-level analytical reasoning. "
            "Consider o1 or GPT-4.1 for most enterprise scenarios."
        ),
    },
    "o4mini": {
        "display": "o4-mini",
        "tier": "Reasoning (Compact)",
        "context_window": "128 K tokens",
        "cost_tier": "Medium",
        "strengths": [
            "Compact reasoning model at reduced cost vs. o3",
            "Good for moderate analytical tasks",
            "Faster than o3 while retaining reasoning quality",
        ],
        "limitations": [
            "Less capable than o3 for highly complex analytical problems",
            "Not optimised for general conversational use",
        ],
        "recommendation": (
            "Good balance of reasoning ability and cost. "
            "Evaluate GPT-4.1 if conversational quality is more important than reasoning depth."
        ),
    },
}

_HINT_TO_OPENAI_MODEL: dict[str, str] = {
    "GPT41": "gpt-4.1",
    "gpt-4.1": "gpt-4.1",
    "gpt41": "gpt-4.1",
    "GPT41Mini": "gpt-4.1-mini",
    "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt41mini": "gpt-4.1-mini",
    "GPT41Nano": "gpt-4.1-nano",
    "gpt-4.1-nano": "gpt-4.1-nano",
    "gpt41nano": "gpt-4.1-nano",
    "GPT5": "gpt-5",
    "gpt-5": "gpt-5",
    "gpt5": "gpt-5",
    "GPT5Chat": "gpt-5-chat",
    "gpt-5-chat": "gpt-5-chat",
    "gpt5chat": "gpt-5-chat",
    "o1": "o1",
    "o1-preview": "o1-preview",
    "o1-mini": "o1-mini",
    "o3": "o3",
    "o3-mini": "o3-mini",
    "o4-mini": "o4-mini",
    "o4mini": "o4-mini",
    "GPT4o": "gpt-4o",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4": "gpt-4",
    "GPT4": "gpt-4",
}

_LEGACY_HINTS = {"GPT4o", "gpt-4o", "gpt-4o-mini", "gpt-4", "GPT4", "gpt-35-turbo", "gpt-3.5-turbo"}

_SAMPLE_QUERIES: list[str] = [
    "What can you help me with?",
    "How do I contact support?",
    "What are your main capabilities?",
    "Can you summarise the key policies relevant to my request?",
    "What should I do if I encounter an error?",
]

_MAX_TOKENS = 200
_OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_catalogue_key(hint: str | None) -> str | None:
    if not hint:
        return None
    normalized = hint.strip()
    if normalized in _MODEL_CATALOGUE:
        return normalized
    from validator import _HINT_TO_KEY  # type: ignore[attr-defined]

    key = _HINT_TO_KEY.get(normalized)
    if key and key in _MODEL_CATALOGUE:
        return key
    return None


def _call_openai_chat(
    model: str,
    system: str,
    user: str,
    api_key: str,
    timeout_s: float = 30.0,
) -> str | None:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or "You are a helpful assistant."},
            {"role": "user", "content": user},
        ],
        "max_tokens": _MAX_TOKENS,
        "temperature": 0.2,
    }

    try:
        resp = httpx.post(
            _OPENAI_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        return body["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, IndexError):
        return None


def _run_api_comparison(
    instructions: str,
    comparison_models: list[str],
    api_key: str,
) -> list[dict]:
    results: list[dict] = []
    system = instructions.strip() if instructions else "You are a helpful assistant."
    for query in _SAMPLE_QUERIES:
        for model in comparison_models:
            response = _call_openai_chat(model, system, query, api_key)
            results.append(
                {
                    "model": model,
                    "query": query,
                    "response": response or "(no response)",
                    "length": len(response) if response else 0,
                }
            )
    return results


def _summarise_api_results(results: list[dict], comparison_models: list[str]) -> str:
    if not results:
        return "_No API comparison results available._\n"

    lines: list[str] = []

    model_stats: dict[str, dict] = {m: {"total_len": 0, "count": 0, "failures": 0} for m in comparison_models}
    for r in results:
        m = r["model"]
        if m not in model_stats:
            continue
        if r["response"] == "(no response)":
            model_stats[m]["failures"] += 1
        else:
            model_stats[m]["total_len"] += r["length"]
            model_stats[m]["count"] += 1

    lines += ["### API Comparison Summary", ""]
    lines += [
        f"We ran {len(_SAMPLE_QUERIES)} sample queries on each model using the agent's system instructions as context.",
        "",
    ]

    lines += [
        "| Model | Avg response length | Failures |",
        "| --- | --- | --- |",
    ]
    for m in comparison_models:
        stats = model_stats[m]
        avg = stats["total_len"] // stats["count"] if stats["count"] > 0 else 0
        lines.append(f"| {m} | {avg} chars | {stats['failures']}/{len(_SAMPLE_QUERIES)} |")
    lines.append("")

    ranked = sorted(
        [
            (m, model_stats[m]["total_len"] // model_stats[m]["count"] if model_stats[m]["count"] > 0 else 0)
            for m in comparison_models
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    if ranked:
        best_model, best_avg = ranked[0]
        other_avgs = [avg for _, avg in ranked[1:] if avg > 0]
        if other_avgs:
            pct_diff = round(((best_avg - other_avgs[0]) / other_avgs[0]) * 100) if other_avgs[0] > 0 else 0
            lines.append(
                f"> **{best_model}** produced the longest responses on average ({best_avg} chars), "
                f"{pct_diff}% more than the next model. Longer responses tend to be more thorough, "
                "but may also be more verbose — review sample outputs for quality."
            )
        else:
            lines.append(f"> **{best_model}** produced the longest responses on average ({best_avg} chars).")
        lines.append("")

    lines += ["### Sample Query Comparison", ""]
    for query in _SAMPLE_QUERIES:
        lines += [f"**Query:** _{query}_", ""]
        for m in comparison_models:
            row = next((r for r in results if r["model"] == m and r["query"] == query), None)
            resp = row["response"] if row else "(no response)"
            short = resp[:200] + "…" if len(resp) > 200 else resp
            lines += [f"- **{m}**: {short}", ""]
    return "\n".join(lines)


def _choose_comparison_models(catalogue_key: str | None, configured_openai_model: str) -> list[str]:
    models: list[str] = []
    if configured_openai_model and configured_openai_model not in ("gpt-4o",):
        models.append(configured_openai_model)
    if "gpt-4o" not in models:
        models.append("gpt-4o")
    if "gpt-4o-mini" not in models and len(models) < 3:
        models.append("gpt-4o-mini")
    seen: list[str] = []
    for m in models:
        if m not in seen:
            seen.append(m)
    return seen[:3]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_comparison_markdown(profile: BotProfile) -> str:
    """Return a Markdown string for the 'Model Performance Comparison' section."""
    lines: list[str] = ["## Model Performance Comparison", ""]

    gpt_info = profile.gpt_info
    hint = (gpt_info.model_hint or "").strip() if gpt_info else ""
    catalogue_key = _resolve_catalogue_key(hint or None)
    model_data = _MODEL_CATALOGUE.get(catalogue_key) if catalogue_key else None

    # 1. Model Identification
    lines += ["### Configured Model", ""]

    if model_data:
        display = model_data["display"]
        tier = model_data["tier"]
        ctx = model_data["context_window"]
        cost = model_data["cost_tier"]
        lines += [
            "| Field | Value |",
            "| --- | --- |",
            f"| **Model** | {display} |",
            f"| **Tier** | {tier} |",
            f"| **Context window** | {ctx} |",
            f"| **Cost tier** | {cost} |",
            "",
        ]
    elif hint and hint in _LEGACY_HINTS:
        lines += [
            f"The agent is configured with **{hint}** — a legacy model that is not part of the "
            "current Copilot Studio GPT-4.1+ catalogue.",
            "",
            "> ⚠️ **Upgrade recommended.** Migrating to GPT-4.1 (or GPT-4.1 Mini for cost savings) "
            "will improve instruction-following accuracy, increase the context window, and align the "
            "agent with actively maintained model generations.",
            "",
        ]
    elif hint:
        lines += [
            f"Configured model hint: **{hint}**  ",
            "_Model not found in the Copilot Studio catalogue.  "
            "Verify the model name in the agent's GPT component configuration._",
            "",
        ]
    else:
        lines += [
            "_No model configuration detected in this snapshot. "
            "Open the agent in Copilot Studio and check Settings → AI Capabilities → Model._",
            "",
        ]

    # 2. Model Catalogue Overview
    lines += ["### Available Copilot Studio Models", ""]
    lines += [
        "| Model | Tier | Context Window | Cost Tier | Best For |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key, meta in _MODEL_CATALOGUE.items():
        strengths_str = meta["strengths"][0] if meta["strengths"] else "—"
        active = " ✅ *(current)*" if key == catalogue_key else ""
        lines.append(
            f"| {meta['display']}{active} | {meta['tier']} | {meta['context_window']} "
            f"| {meta['cost_tier']} | {strengths_str} |"
        )
    lines.append("")

    # 3. Recommendation
    lines += ["### Recommendation", ""]
    if model_data:
        lines += [
            f"**Current model:** {model_data['display']}",
            "",
            f"{model_data['recommendation']}",
            "",
            "**Strengths:**",
            "",
        ]
        for s in model_data["strengths"]:
            lines.append(f"- {s}")
        lines += ["", "**Considerations:**", ""]
        for lim in model_data["limitations"]:
            lines.append(f"- {lim}")
        lines.append("")
    elif hint and hint in _LEGACY_HINTS:
        lines += [
            "**Upgrade path:**",
            "",
            "- **GPT-4.1** — best accuracy, 1 M-token context. Recommended for complex agents.",
            "- **GPT-4.1 Mini** — good balance of quality and cost for well-scoped agents.",
            "- **GPT-4.1 Nano** — lowest cost, fastest. Ideal for simple FAQ / routing agents.",
            "",
        ]
    else:
        lines += [
            "Configure the agent's foundation model in Copilot Studio under "
            "**Settings → AI Capabilities → Model** before evaluating model performance.",
            "",
        ]

    # 4. API-Based Comparison (optional)
    enable_api = os.getenv("MCS_ENABLE_MODEL_COMPARISON", "").strip().lower() in ("1", "true", "yes")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    lines += ["### Live API Comparison", ""]

    if not enable_api:
        lines += [
            "_Live model comparison is disabled._  ",
            "Set `MCS_ENABLE_MODEL_COMPARISON=true` and `OPENAI_API_KEY=<key>` in the environment "
            "to run sample queries against multiple models and compare responses automatically.",
            "",
        ]
    elif not api_key:
        lines += [
            "> ⚠️ `MCS_ENABLE_MODEL_COMPARISON` is set but `OPENAI_API_KEY` is not provided. "
            "Provide a valid OpenAI API key to enable live comparison.",
            "",
        ]
    else:
        configured_openai = _HINT_TO_OPENAI_MODEL.get(hint, "gpt-4o") if hint else "gpt-4o"
        comparison_models = _choose_comparison_models(catalogue_key, configured_openai)

        instructions = (gpt_info.instructions or "") if gpt_info else ""

        lines += [
            f"Running {len(_SAMPLE_QUERIES)} sample queries on "
            f"{', '.join('**' + m + '**' for m in comparison_models)} …",
            "",
        ]

        try:
            results = _run_api_comparison(instructions, comparison_models, api_key)
            lines.append(_summarise_api_results(results, comparison_models))
        except Exception as exc:  # noqa: BLE001
            lines += [
                f"> ⚠️ API comparison failed: {exc}",
                "",
            ]

    return "\n".join(lines)
