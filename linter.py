from loguru import logger
from openai import AsyncOpenAI

from models import BotProfile

# Map Copilot Studio model hints to OpenAI model IDs.
# Easy to expand — one line per new hint as we discover them from bot exports.
MODEL_HINT_MAP: dict[str, str] = {
    "GPT41": "gpt-4.1",
    "GPT4o": "gpt-4.1",
    "GPT4oMini": "gpt-4.1-mini",
    "GPT35Turbo": "gpt-3.5-turbo",
}

# Fallback model when hint is unknown or None.
_FALLBACK_MODEL = "gpt-4.1"


def resolve_model(hint: str | None) -> tuple[str, bool]:
    """Resolve a Copilot Studio model hint to an OpenAI model ID.

    Returns (model_id, was_fallback).
    """
    if hint and hint in MODEL_HINT_MAP:
        return MODEL_HINT_MAP[hint], False
    logger.warning(f"Unknown model hint '{hint}', falling back to {_FALLBACK_MODEL}")
    return _FALLBACK_MODEL, True


LINT_SYSTEM_PROMPT = """\
You are an expert Microsoft Copilot Studio architect performing a thorough instruction audit.

You will receive a JSON payload describing a Copilot Studio bot: its name, whether it's an orchestrator, its model hint, system instructions, GPT description, component inventory, and topic connection graph.

Produce a structured Markdown lint report covering EVERY section below. For each section, give a severity (✅ Pass, ⚠️ Warning, ❌ Fail) and concrete, actionable findings. If a section has no issues, still include it with ✅ Pass and a one-liner.

---

## 1. Instruction Clarity & Completeness
- Are the system instructions clear, unambiguous, and complete?
- Do they define the bot's persona, boundaries, and escalation behavior?
- Are there conflicting or contradictory instructions?
- Is the tone/voice consistent?

## 2. Guardrails & Safety
- Does the bot have clear boundaries on what it should NOT do?
- Are there instructions preventing prompt injection, jailbreaking, or off-topic abuse?
- Is content moderation configured appropriately?
- Are there PII handling instructions if applicable?

## 3. Grounding & Knowledge Configuration
- Is the knowledge source configuration appropriate (web browsing, code interpreter, knowledge sources)?
- Are there instructions for when the bot doesn't know the answer?
- Is hallucination risk addressed (e.g., "only answer from provided knowledge")?

## 4. Topic Architecture & Routing
- Is the topic structure logical and maintainable?
- Are there orphaned topics (no inbound connections)?
- Are there dead-end topics (no outbound connections and no resolution)?
- Is the routing between topics clear and complete?
- For orchestrators: are agent/task delegations well-defined?

## 5. Component Health
- Are there disabled/inactive components that should be cleaned up?
- Are component descriptions filled in (important for AI routing)?
- Is the component count reasonable or is there sprawl?

## 6. Model Configuration
- Is the selected model appropriate for the bot's complexity?
- Are there capabilities enabled that aren't needed (unnecessary cost)?
- Are there capabilities missing that the instructions assume?

## 7. Error Handling & Fallback
- Do the instructions define fallback behavior?
- Is there a graceful degradation path when the AI can't help?
- Are error messages user-friendly?

## 8. Orchestration Quality (if orchestrator)
- Is the delegation between agents/tasks clear?
- Are handoff conditions well-defined?
- Is there a risk of routing loops?

## 9. Quick Wins
List the top 3-5 highest-impact improvements that can be made with minimal effort.

---

Be specific. Quote the problematic instruction text when pointing out issues. Suggest concrete rewrites where appropriate. Keep the report professional and actionable.
"""


def build_component_payload(profile: BotProfile) -> dict:
    """Build the JSON payload sent to the LLM for linting."""
    components = [comp.model_dump() for comp in profile.components]
    topic_connections = [tc.model_dump() for tc in profile.topic_connections]

    payload: dict = {
        "bot_name": profile.display_name,
        "is_orchestrator": profile.is_orchestrator,
        "model_hint": None,
        "instructions": None,
        "gpt_description": None,
        "components": components,
        "topic_connections": topic_connections,
    }

    if profile.gpt_info:
        payload["model_hint"] = profile.gpt_info.model_hint
        payload["instructions"] = profile.gpt_info.instructions
        payload["gpt_description"] = profile.gpt_info.description

    return payload


async def run_lint(profile: BotProfile, api_key: str) -> tuple[str, str]:
    """Run the instruction lint against the OpenAI API.

    Returns (markdown_report, model_used).
    """
    hint = profile.gpt_info.model_hint if profile.gpt_info else None
    model_id, was_fallback = resolve_model(hint)

    payload = build_component_payload(profile)

    import json

    user_content = json.dumps(payload, indent=2, default=str)

    client = AsyncOpenAI(api_key=api_key)

    logger.info(f"Running lint with model {model_id} (fallback={was_fallback})")

    response = await client.chat.completions.create(
        model=model_id,
        temperature=0.3,
        messages=[
            {"role": "system", "content": LINT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )

    report = response.choices[0].message.content or ""

    fallback_note = " (fallback — unknown model hint)" if was_fallback else ""
    header = f"> Lint performed by `{model_id}`{fallback_note}\n\n"

    return header + report, model_id
