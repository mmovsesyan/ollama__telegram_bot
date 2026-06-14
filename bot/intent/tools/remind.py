from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.services.reminders import _process_remind


class RemindTool(BaseTool):
    name = "remind"
    required_args = ("content",)

    async def execute(self, context: ToolContext) -> ToolResult:
        # Always feed the FULL user text into _process_remind so its time-parser
        # sees "через час позвонить" rather than just "позвонить" — the LLM's
        # extracted args.content drops time tokens we still need.
        text = (context.message_text or "").strip()
        if not text:
            return ToolResult(text="Не удалось определить текст напоминания", success=False)
        await _process_remind(user_id=context.user_id, text=text, action="notify")
        return ToolResult(text="", success=True)

