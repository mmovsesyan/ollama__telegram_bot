from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.routers.cron import _process_remind


class RemindTool(BaseTool):
    name = "remind"
    required_args = ("content",)

    async def execute(self, context: ToolContext) -> ToolResult:
        content = context.args.content or context.message_text
        await _process_remind(user_id=context.user_id, text=content, action="notify")
        return ToolResult(text="reminder_created", success=True)
