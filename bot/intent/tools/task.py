from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.routers.cron import _process_task_from_text


class TaskTool(BaseTool):
    name = "task"
    required_args = ("content",)

    async def execute(self, context: ToolContext) -> ToolResult:
        content = context.args.content or context.message_text
        await _process_task_from_text(user_id=context.user_id, text=content)
        return ToolResult(text="task_created", success=True)
