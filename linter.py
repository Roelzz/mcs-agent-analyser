import json

from anthropic import AsyncAnthropic
from loguru import logger
from openai import AsyncOpenAI

from models import BotProfile

# (provider, model_id) — provider is "openai" or "anthropic"
# Multiple hint formats per model: PascalCase, kebab-case, lowercase (matching validator.py convention).
MODEL_HINT_MAP: dict[str, tuple[str, str]] = {
    # OpenAI — legacy
    "GPT41": ("openai", "gpt-4.1"),
    "gpt-4.1": ("openai", "gpt-4.1"),
    "gpt41": ("openai", "gpt-4.1"),
    "GPT4o": ("openai", "gpt-4.1"),
    "gpt-4o": ("openai", "gpt-4.1"),
    "GPT4oMini": ("openai", "gpt-4.1-mini"),
    "gpt-4o-mini": ("openai", "gpt-4.1-mini"),
    "GPT35Turbo": ("openai", "gpt-3.5-turbo"),
    "gpt-3.5-turbo": ("openai", "gpt-3.5-turbo"),
    # OpenAI — current (from Copilot Studio model picker)
    "GPT5Chat": ("openai", "gpt-5"),
    "gpt-5-chat": ("openai", "gpt-5"),
    "gpt5chat": ("openai", "gpt-5"),
    "GPT5Auto": ("openai", "gpt-5"),
    "gpt-5-auto": ("openai", "gpt-5"),
    "GPT5Reasoning": ("openai", "gpt-5"),
    "gpt-5-reasoning": ("openai", "gpt-5"),
    "GPT53Chat": ("openai", "gpt-5"),
    "gpt-5.3-chat": ("openai", "gpt-5"),
    "GPT54Reasoning": ("openai", "gpt-5"),
    "gpt-5.4-reasoning": ("openai", "gpt-5"),
    # Anthropic (using aliases — no date suffix needed)
    "Sonnet45": ("anthropic", "claude-sonnet-4-5"),
    "sonnet4-5": ("anthropic", "claude-sonnet-4-5"),
    "sonnet45": ("anthropic", "claude-sonnet-4-5"),
    "claude-sonnet-4-5": ("anthropic", "claude-sonnet-4-5"),
    "Sonnet46": ("anthropic", "claude-sonnet-4-6"),
    "sonnet4-6": ("anthropic", "claude-sonnet-4-6"),
    "sonnet46": ("anthropic", "claude-sonnet-4-6"),
    "claude-sonnet-4-6": ("anthropic", "claude-sonnet-4-6"),
    "Opus46": ("anthropic", "claude-opus-4-6"),
    "opus4-6": ("anthropic", "claude-opus-4-6"),
    "opus46": ("anthropic", "claude-opus-4-6"),
    "claude-opus-4-6": ("anthropic", "claude-opus-4-6"),
}

_FALLBACK_PROVIDER = "openai"
_FALLBACK_MODEL = "gpt-4.1"


def resolve_model(hint: str | None) -> tuple[str, str, bool]:
    """Resolve a Copilot Studio model hint to (provider, model_id, was_fallback)."""
    if hint:
        if hint in MODEL_HINT_MAP:
            provider, model_id = MODEL_HINT_MAP[hint]
            return provider, model_id, False
        # Case-insensitive fallback
        lower = hint.lower()
        for key, value in MODEL_HINT_MAP.items():
            if key.lower() == lower:
                return value[0], value[1], False
    logger.warning(f"Unknown model hint '{hint}', falling back to {_FALLBACK_PROVIDER}/{_FALLBACK_MODEL}")
    return _FALLBACK_PROVIDER, _FALLBACK_MODEL, True


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


async def _lint_openai(api_key: str, model_id: str, user_content: str) -> str:
    """Run lint via OpenAI API."""
    client = AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model=model_id,
        temperature=0.3,
        messages=[
            {"role": "system", "content": LINT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content or ""


async def _lint_anthropic(api_key: str, model_id: str, user_content: str) -> str:
    """Run lint via Anthropic API."""
    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=model_id,
        max_tokens=4096,
        temperature=0.3,
        system=LINT_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_content},
        ],
    )
    return response.content[0].text


async def run_lint(
    profile: BotProfile,
    openai_api_key: str = "",
    anthropic_api_key: str = "",
) -> tuple[str, str]:
    """Run the instruction lint against the resolved provider's API.

    Returns (markdown_report, model_used).
    """
    hint = profile.gpt_info.model_hint if profile.gpt_info else None
    provider, model_id, was_fallback = resolve_model(hint)

    payload = build_component_payload(profile)
    user_content = json.dumps(payload, indent=2, default=str)

    logger.info(f"Running lint with {provider}/{model_id} (fallback={was_fallback})")

    if provider == "anthropic":
        if not anthropic_api_key:
            raise ValueError(f"Bot uses Anthropic model '{model_id}' but ANTHROPIC_API_KEY is not set.")
        report = await _lint_anthropic(anthropic_api_key, model_id, user_content)
    else:
        if not openai_api_key:
            raise ValueError(f"Bot uses OpenAI model '{model_id}' but OPENAI_API_KEY is not set.")
        report = await _lint_openai(openai_api_key, model_id, user_content)

    fallback_note = " (fallback — unknown model hint)" if was_fallback else ""
    header = f"> Lint performed by `{model_id}`{fallback_note}\n\n"

    return header + report, model_id
