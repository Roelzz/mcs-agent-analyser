from enum import Enum

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


# --- Bot Profile models (from YAML) ---


class AISettings(BaseModel):
    use_model_knowledge: bool = False
    file_analysis: bool = False
    semantic_search: bool = False
    content_moderation: str = "Unknown"
    opt_in_latest_models: bool = False


class ComponentSummary(BaseModel):
    kind: str
    display_name: str
    schema_name: str
    state: str = "Active"
    trigger_kind: str | None = None
    dialog_kind: str | None = None
    action_kind: str | None = None
    description: str | None = None
    model_description: str | None = None
    trigger_queries: list[str] = Field(default_factory=list)
    action_summary: dict[str, int] = Field(default_factory=dict)
    action_details: list[dict] = Field(default_factory=list)
    has_external_calls: bool = False
    source_kind: str | None = None
    source_site: str | None = None
    # Tool classification (TaskDialog/AgentDialog)
    tool_type: str | None = None
    connection_reference: str | None = None
    operation_id: str | None = None
    connection_mode: str | None = None
    external_agent_protocol: str | None = None
    connected_bot_schema: str | None = None
    agent_instructions: str | None = None
    connector_display_name: str | None = None
    # Component-specific metadata
    entity_kind: str | None = None
    entity_item_count: int = 0
    file_type: str | None = None
    variable_scope: str | None = None
    trigger_condition_raw: str | None = None
    # Raw dialog dict — populated only for DialogComponent. The topic-settings
    # explainer walks this tree to produce per-action explanations. Kept loose
    # (Any) because the underlying YAML schema is open-ended.
    raw_dialog: dict | None = None


class GptInfo(BaseModel):
    display_name: str = ""
    description: str | None = None
    instructions: str | None = None
    model_hint: str | None = None
    knowledge_sources_kind: str | None = None
    web_browsing: bool = False
    code_interpreter: bool = False
    conversation_starters: list[dict] = Field(default_factory=list)


class TopicConnection(BaseModel):
    source_schema: str
    source_display: str
    target_schema: str
    target_display: str
    condition: str | None = None


class AppInsightsConfig(BaseModel):
    configured: bool = False
    log_activities: bool = False
    log_sensitive_properties: bool = False


class BotProfile(BaseModel):
    schema_name: str = ""
    bot_id: str = ""
    display_name: str = ""
    channels: list[str] = Field(default_factory=list)
    ai_settings: AISettings = Field(default_factory=AISettings)
    recognizer_kind: str = "Unknown"
    agent_model: str | None = None
    components: list[ComponentSummary] = Field(default_factory=list)
    environment_variables: list[dict] = Field(default_factory=list)
    flows: list[dict] = Field(default_factory=list)
    connectors: list[dict] = Field(default_factory=list)
    is_orchestrator: bool = False
    gpt_info: GptInfo | None = None
    topic_connections: list[TopicConnection] = Field(default_factory=list)
    # Entity-level properties (Phase 1)
    authentication_mode: str = "Unknown"
    authentication_trigger: str = "Unknown"
    access_control_policy: str = "Unknown"
    generative_actions_enabled: bool = False
    is_agent_connectable: bool = False
    is_lightweight_bot: bool = False
    app_insights: AppInsightsConfig | None = None
    # Connection infrastructure (Phase 3)
    connection_references: list[dict] = Field(default_factory=list)
    connector_definitions: list[dict] = Field(default_factory=list)


# --- Timeline models (from dialog.json) ---


class EventType(str, Enum):
    USER_MESSAGE = "UserMessage"
    BOT_MESSAGE = "BotMessage"
    PLAN_RECEIVED = "PlanReceived"
    PLAN_RECEIVED_DEBUG = "PlanReceivedDebug"
    STEP_TRIGGERED = "StepTriggered"
    STEP_FINISHED = "StepFinished"
    PLAN_FINISHED = "PlanFinished"
    DIALOG_TRACING = "DialogTracing"
    KNOWLEDGE_SEARCH = "KnowledgeSearch"
    VARIABLE_ASSIGNMENT = "VariableAssignment"
    DIALOG_REDIRECT = "DialogRedirect"
    ACTION_HTTP_REQUEST = "ActionHttpRequest"
    ACTION_QA = "ActionQA"
    ACTION_TRIGGER_EVAL = "ActionTriggerEval"
    ACTION_BEGIN_DIALOG = "ActionBeginDialog"
    ACTION_SEND_ACTIVITY = "ActionSendActivity"
    ORCHESTRATOR_THINKING = "OrchestratorThinking"
    INTENT_RECOGNITION = "IntentRecognition"
    GENERATIVE_ANSWER = "GenerativeAnswer"
    ERROR = "Error"
    OTHER = "Other"


class TimelineEvent(BaseModel):
    timestamp: str | None = None
    position: int = 0
    event_type: EventType = EventType.OTHER
    topic_name: str | None = None
    summary: str = ""
    state: str | None = None
    error: str | None = None
    step_id: str | None = None
    plan_identifier: str | None = None
    raw_type: str | None = None
    thought: str | None = None
    is_final_plan: bool | None = None
    has_recommendations: bool | None = None
    plan_used_outputs: str | None = None
    orchestrator_ask: str | None = None
    plan_steps: list[str] = Field(default_factory=list)
    intent_score: float | None = None


class ExecutionPhase(BaseModel):
    label: str
    phase_type: str = ""
    start: str | None = None
    end: str | None = None
    duration_ms: float = 0.0
    state: str = "completed"


class SearchResult(BaseModel):
    name: str | None = None
    url: str | None = None
    text: str | None = None  # snippet
    file_type: str | None = None
    result_type: str | None = None  # e.g. "SharepointSiteSearch"
    rank_score: float | None = None
    verified_rank_score: float | None = None


class KnowledgeSearchInfo(BaseModel):
    position: int = 0
    timestamp: str | None = None
    search_query: str | None = None
    search_keywords: str | None = None
    knowledge_sources: list[str] = Field(default_factory=list)
    execution_time: str | None = None
    thought: str | None = None
    search_results: list[SearchResult] = Field(default_factory=list)
    output_knowledge_sources: list[str] = Field(default_factory=list)
    search_errors: list[str] = Field(default_factory=list)
    triggering_user_message: str | None = None


class GenerativeAnswerCitation(BaseModel):
    url: str | None = None
    snippet: str | None = None
    title: str | None = None


class GenerativeAnswerTrace(BaseModel):
    """Diagnostic data from a topic-level SearchAndSummarizeContent node.

    Captured from the `GenerativeAnswersSupportData` event emitted when a
    topic invokes SearchAndSummarizeContent directly (not via the
    orchestrator's UniversalSearchTool).
    """

    position: int = 0
    timestamp: str | None = None
    topic_name: str | None = None
    triggering_user_message: str | None = None
    activity_id: str | None = None
    # retry chain — attempt 1 = original, attempt 2+ = orchestrator retry on the same user turn
    attempt_index: int = 1
    is_retry: bool = False
    previous_attempt_state: str | None = None
    # query transformation chain
    original_message: str | None = None
    screened_message: str | None = None
    rewritten_message: str | None = None
    rewritten_keywords: str | None = None
    hypothetical_snippet_query: str | None = None
    # LLM resource usage
    rewrite_prompt_tokens: int | None = None
    rewrite_completion_tokens: int | None = None
    rewrite_total_tokens: int | None = None
    rewrite_cached_tokens: int | None = None
    rewrite_model: str | None = None
    rewrite_system_prompt: str | None = None
    rewrite_raw_response: str | None = None
    summarize_prompt_tokens: int | None = None
    summarize_completion_tokens: int | None = None
    summarize_total_tokens: int | None = None
    summarize_cached_tokens: int | None = None
    summarize_model: str | None = None
    summarize_system_prompt: str | None = None
    text_summary: str | None = None
    raw_summary: str | None = None
    # search execution
    endpoints: list[str] = Field(default_factory=list)
    search_results: list[SearchResult] = Field(default_factory=list)
    shadow_search_results: list[SearchResult] = Field(default_factory=list)
    search_errors: list[str] = Field(default_factory=list)
    search_logs: list[str] = Field(default_factory=list)
    search_terms_used: list[str] = Field(default_factory=list)
    shadow_search_terms: list[str] = Field(default_factory=list)
    shadow_search_logs: list[str] = Field(default_factory=list)
    shadow_search_errors: list[str] = Field(default_factory=list)
    search_type: str | None = None
    # generated answer
    summary_text: str | None = None
    citations: list[GenerativeAnswerCitation] = Field(default_factory=list)
    # safety / state
    performed_content_moderation: bool = False
    performed_content_provenance: bool = False
    contains_confidential: bool = False
    filtered_summary: str | None = None
    screened_summary: str | None = None
    gpt_answer_state: str | None = None
    completion_state: str | None = None
    triggered_fallback: bool = False


class CustomSearchStep(BaseModel):
    task_dialog_id: str
    display_name: str = ""
    thought: str | None = None
    status: str = "unknown"  # "inProgress", "completed", "failed"
    error: str | None = None
    execution_time: str | None = None


# --- Tool call analysis models ---


class ToolCallObservation(BaseModel):
    """Parsed tool response from DynamicPlanStepFinished."""

    content: list = Field(default_factory=list)
    structured_content: dict | None = None
    raw_json: str | None = None


class ToolCall(BaseModel):
    """A single tool invocation correlated from Triggered -> BindUpdate -> Finished."""

    step_id: str = ""
    plan_identifier: str | None = None
    task_dialog_id: str = ""
    display_name: str = ""
    tool_type: str | None = None  # MCPServer, ConnectorTool, ChildAgent, etc.
    step_type: str = ""  # LlmSkill, CustomTopic, Agent, KnowledgeSource
    thought: str | None = None
    arguments: dict[str, str] = Field(default_factory=dict)
    observation: ToolCallObservation | None = None
    state: str = ""  # completed, failed, inProgress
    error: str | None = None
    execution_time: str | None = None  # .NET TimeSpan
    duration_ms: float = 0.0
    trigger_timestamp: str | None = None
    finish_timestamp: str | None = None
    position: int = 0
    chain_id: str | None = None  # set by async chain detection


class ToolCallChain(BaseModel):
    """A group of related tool calls detected as an async/polling pattern."""

    chain_id: str
    task_dialog_id: str
    display_name: str
    calls: list[ToolCall] = Field(default_factory=list)
    correlation_keys: list[str] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    final_state: str = ""
    status_progression: list[str] = Field(default_factory=list)


class ToolStatistics(BaseModel):
    """Per-tool aggregate statistics."""

    tool_name: str
    tool_type: str | None = None
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    min_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    total_duration_ms: float = 0.0


class ConversationTimeline(BaseModel):
    bot_name: str = ""
    conversation_id: str = ""
    user_query: str = ""
    events: list[TimelineEvent] = Field(default_factory=list)
    phases: list[ExecutionPhase] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    total_elapsed_ms: float = 0.0
    knowledge_searches: list[KnowledgeSearchInfo] = Field(default_factory=list)
    custom_search_steps: list[CustomSearchStep] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    generative_answer_traces: list[GenerativeAnswerTrace] = Field(default_factory=list)


# --- Credit estimation models ---


class CreditLineItem(BaseModel):
    step_name: str
    step_type: str  # "generative_answer", "classic_answer", "agent_action", "flow_action"
    credits: float
    detail: str = ""
    position: int = 0


class CreditEstimate(BaseModel):
    line_items: list[CreditLineItem] = Field(default_factory=list)
    total_credits: float = 0.0
    warnings: list[str] = Field(default_factory=list)


# --- Custom rule engine models ---

_VALID_OPERATORS = frozenset(
    {"eq", "ne", "gt", "lt", "gte", "lte", "contains", "not_contains", "matches", "exists", "not_exists"}
)


class RuleCondition(BaseModel):
    field: str  # dotted path: "app_insights.configured", "components[].tool_type"
    operator: str  # eq, ne, gt, lt, gte, lte, contains, not_contains, matches, exists, not_exists
    value: str | int | float | bool | list | None = None

    @field_validator("operator")
    @classmethod
    def operator_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_OPERATORS:
            raise ValueError(f"Invalid operator '{v}'. Must be one of: {sorted(_VALID_OPERATORS)}")
        return v


_VALID_SEVERITIES = frozenset({"warning", "fail", "info", "pass"})


class CustomRule(BaseModel):
    rule_id: str
    category: str = "Custom"
    severity: str  # warning, fail, info
    message: str
    condition: RuleCondition

    @field_validator("severity")
    @classmethod
    def severity_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_SEVERITIES:
            raise ValueError(f"Invalid severity '{v}'. Must be one of: {sorted(_VALID_SEVERITIES)}")
        return v


# --- Bot comparison models ---


class ComponentChange(BaseModel):
    schema_name: str
    display_name: str
    field: str
    value_a: str
    value_b: str


class BotDiffResult(BaseModel):
    bot_a_name: str
    bot_b_name: str
    added_components: list[str] = Field(default_factory=list)
    removed_components: list[str] = Field(default_factory=list)
    changed_components: list[ComponentChange] = Field(default_factory=list)
    instruction_diff: str = ""
    connection_changes: list[str] = Field(default_factory=list)
    settings_changes: list[str] = Field(default_factory=list)
    summary_markdown: str = ""


# --- Instruction versioning models ---


class InstructionSnapshot(BaseModel):
    bot_identity: str  # bot_id or schema_name
    bot_name: str
    timestamp: str  # ISO format
    instructions: str | None = None
    instructions_hash: str = ""  # sha256 hex
    gpt_description: str | None = None


class InstructionDiff(BaseModel):
    bot_identity: str
    from_timestamp: str
    to_timestamp: str
    instructions_changed: bool
    description_changed: bool
    unified_diff: str = ""
    change_ratio: float = 0.0  # 0.0-1.0
    is_significant: bool = False  # True if change_ratio > 0.2


# --- Batch analytics models ---


class TopicUsage(BaseModel):
    topic_name: str
    invocation_count: int = 0
    avg_duration_ms: float = 0.0
    error_count: int = 0


class FailureMode(BaseModel):
    error_pattern: str
    count: int = 0
    example_conversation_ids: list[str] = Field(default_factory=list)


class BatchAnalyticsSummary(BaseModel):
    conversation_count: int = 0
    avg_elapsed_ms: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    escalation_count: int = 0
    success_rate: float = 0.0
    escalation_rate: float = 0.0
    topic_usage: list[TopicUsage] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    total_credits_estimated: float = 0.0
    avg_credits_per_conversation: float = 0.0


# --- Renamer models ---


class RenameConfig(BaseModel):
    """Configuration for a solution rename operation."""

    source_path: Path
    new_agent_name: str
    new_solution_name: str
    new_bot_schema_name: str | None = None
    output_path: Path
    new_solution_display_name: str | None = None
    old_agent_name_override: str | None = None
    old_solution_name_override: str | None = None

    @field_validator("new_agent_name", "new_solution_name")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("new_solution_name")
    @classmethod
    def solution_name_valid(cls, v: str) -> str:
        """Solution unique names must be alphanumeric (no spaces, hyphens only)."""
        import re

        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,99}$", v):
            raise ValueError(
                "Solution unique name must start with a letter and contain only "
                "letters, digits, and underscores (max 100 characters)."
            )
        return v

    @field_validator("new_bot_schema_name")
    @classmethod
    def schema_name_valid(cls, v: str | None) -> str | None:
        import re

        if v is None:
            return v
        if not re.match(r"^[a-z][a-z0-9_]{0,99}$", v):
            raise ValueError(
                "Bot schema name must be lowercase, start with a letter, and contain "
                "only lowercase letters, digits, and underscores (max 100 characters)."
            )
        return v


class SolutionInfo(BaseModel):
    """Metadata detected from an existing solution export."""

    bot_schema_name: str
    bot_display_name: str
    solution_unique_name: str
    solution_display_name: str
    botcomponent_folders: list[str] = []


class RenameResult(BaseModel):
    """Result of a completed rename operation."""

    old_bot_schema: str
    new_bot_schema: str
    old_solution_name: str
    new_solution_name: str
    old_agent_name: str
    new_agent_name: str
    files_modified: int
    folders_renamed: int
    output_path: Path
    warnings: list[str] = []
