from typing import Any, Literal
from pydantic import BaseModel, Field


class IntentArgs(BaseModel):
    content: str | None = None
    trigger_at: str | None = None
    recurring: str | None = None
    query: str | None = None
    city: str | None = None
    url: str | None = None
    name: str | None = None
    interval: int | None = None
    plan_text: str | None = None
    days: int | None = None


ALLOWED_INTENTS = Literal[
    "chat",
    "create_reminder",
    "create_task",
    "add_memory",
    "add_note",
    "search",
    "weather",
    "news",
    "add_monitor",
    "generate_plan",
    "kb_search",
    "clarify",
    "cancel",
    "help",
]

ALLOWED_TOOLS = Literal[
    "chat",
    "remind",
    "task",
    "memory",
    "note",
    "search",
    "weather",
    "news",
    "monitor",
    "plan",
    "kb_search",
]


class IntentResult(BaseModel):
    intent: ALLOWED_INTENTS
    tool: ALLOWED_TOOLS
    args: IntentArgs = Field(default_factory=IntentArgs)
    confidence: float = Field(ge=0.0, le=1.0)
    clarification_needed: bool = False
    clarification_question: str | None = None
    proactive_suggestion: dict[str, Any] | None = None
    response_tone: Literal["friendly", "neutral", "concise"] = "friendly"


class ToolContext(BaseModel):
    user_id: int
    message_text: str
    args: IntentArgs
    intent_result: IntentResult
    db: Any | None = None
    state: Any | None = None
    message: Any | None = None  # aiogram Message, used by tools that stream replies
    model_config = {"arbitrary_types_allowed": True}


class ToolResult(BaseModel):
    text: str
    success: bool = True
    reply_markup: Any | None = None
    extra: dict[str, Any] | None = None
    model_config = {"arbitrary_types_allowed": True}
