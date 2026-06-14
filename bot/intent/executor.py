import logging
from typing import Any
from bot.intent.schemas import IntentArgs, IntentResult, ToolContext, ToolResult
from bot.intent.tools.chat import ChatTool
from bot.intent.tools.registry import ToolRegistry
from bot.intent.validator import ValidationError, Validator

logger = logging.getLogger(__name__)


_FRIENDLY_HINTS = {
    "remind": (
        "⏰ Чтобы создать напоминание, скажи что и когда:\n"
        "• «напомни через 5 минут позвонить»\n"
        "• «завтра в 9:00 проверить отчёт»\n"
        "• «каждый день в 7 утра показывать новости»"
    ),
    "task": (
        "📋 Чтобы создать задачу для AI, скажи что и когда:\n"
        "• «задача через час найти новости Tesla»\n"
        "• «каждое утро в 8 пришли погоду в Москве»"
    ),
    "weather": (
        "🌤 Скажи город:\n"
        "• «погода в Москве»\n"
        "• «weather in London»"
    ),
    "monitor": (
        "📡 Скажи имя и адрес сайта:\n"
        "• «следи за Google по адресу google.com»\n"
        "• «мониторь GitHub github.com каждые 5 минут»"
    ),
    "memory": (
        "🧠 Скажи что запомнить:\n"
        "• «запомни, я люблю краткие ответы»\n"
        "• «факт: я работаю над проектом X»"
    ),
    "note": (
        "📝 Скажи что записать:\n"
        "• «заметка: купить акции TSLA»\n"
        "• «запиши, забрать посылку до пятницы»"
    ),
    "search": (
        "🔍 Что искать?\n"
        "• «поищи последние новости Tesla»"
    ),
}


def _friendly_clarification(intent_result: IntentResult, reason: str) -> str:
    """Turn a Validator failure into an actionable hint with examples."""
    tool_hint = _FRIENDLY_HINTS.get(intent_result.tool)
    if tool_hint:
        return f"❓ Не хватает деталей. {tool_hint}"
    # Generic fallback when no per-tool hint is registered.
    return f"❓ Не уверен, что ты имел в виду. Уточни, пожалуйста.\n\n_({reason})_"


class IntentExecutor:
    """Validate an intent result and dispatch it to the correct tool."""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or ToolRegistry()
        self.chat_tool = ChatTool()

    async def execute(
        self,
        user_id: int,
        message_text: str,
        intent_result: IntentResult,
        db: Any | None = None,
        state: Any | None = None,
        message: Any | None = None,
    ) -> ToolResult:
        # If the LLM explicitly asked for clarification, short-circuit before validation.
        if intent_result.clarification_needed:
            question = intent_result.clarification_question or "Не уверен, что ты имел в виду. Можешь уточнить?"
            return ToolResult(
                text=question,
                success=True,
                extra={"reason": "clarification_needed"},
            )

        try:
            Validator.validate(intent_result)
        except ValidationError as exc:
            reason = str(exc)
            return ToolResult(
                text=_friendly_clarification(intent_result, reason),
                success=True,
                extra={"reason": reason},
            )

        tool = self.registry.get(intent_result.tool)
        if tool is None:
            chat_context = ToolContext(
                user_id=user_id,
                message_text=message_text,
                args=IntentArgs(),
                intent_result=IntentResult(
                    intent="chat",
                    tool="chat",
                    args=IntentArgs(),
                    confidence=1.0,
                ),
                db=db,
                state=state,
                message=message,
            )
            return await self.chat_tool.execute(chat_context)

        context = ToolContext(
            user_id=user_id,
            message_text=message_text,
            args=intent_result.args,
            intent_result=intent_result,
            db=db,
            state=state,
            message=message,
        )
        try:
            return await tool.execute(context)
        except Exception:
            logger.exception("Tool execution failed for tool=%s", intent_result.tool)
            return await self.chat_tool.execute(context)
