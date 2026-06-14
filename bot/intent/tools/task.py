from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.services.reminders import _process_task_from_text


class TaskTool(BaseTool):
    name = "task"
    required_args = ("content",)

    async def execute(self, context: ToolContext) -> ToolResult:
        # Use full message_text so time tokens survive the LLM's content extraction.
        text = (context.message_text or "").strip()
        if not text:
            return ToolResult(text="Не удалось определить текст задачи", success=False)
        await _process_task_from_text(user_id=context.user_id, text=text)
        return ToolResult(text="", success=True)

