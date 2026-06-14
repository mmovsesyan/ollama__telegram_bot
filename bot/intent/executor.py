from bot.intent.schemas import IntentArgs, IntentResult, ToolContext, ToolResult
from bot.intent.tools.chat import ChatTool
from bot.intent.tools.registry import ToolRegistry
from bot.intent.validator import ValidationError, Validator


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
    ) -> ToolResult:
        try:
            Validator.validate(intent_result)
        except ValidationError as exc:
            reason = str(exc)
            return ToolResult(
                text=f"Не уверен, что ты имел в виду. Можешь уточнить? ({reason})",
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
            )
            return await self.chat_tool.execute(chat_context)

        context = ToolContext(
            user_id=user_id,
            message_text=message_text,
            args=intent_result.args,
            intent_result=intent_result,
        )
        return await tool.execute(context)
