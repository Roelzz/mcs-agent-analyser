from enum import Enum

from pydantic import BaseModel, Field


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


class GptInfo(BaseModel):
    display_name: str = ""
    description: str | None = None
    instructions: str | None = None
    model_hint: str | None = None
    knowledge_sources_kind: str | None = None
    web_browsing: bool = False
    code_interpreter: bool = False


class TopicConnection(BaseModel):
    source_schema: str
    source_display: str
    target_schema: str
    target_display: str
    condition: str | None = None


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


class ExecutionPhase(BaseModel):
    label: str
    phase_type: str = ""
    start: str | None = None
    end: str | None = None
    duration_ms: float = 0.0
    state: str = "completed"


class ConversationTimeline(BaseModel):
    bot_name: str = ""
    conversation_id: str = ""
    user_query: str = ""
    events: list[TimelineEvent] = Field(default_factory=list)
    phases: list[ExecutionPhase] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    total_elapsed_ms: float = 0.0
