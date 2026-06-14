from bot.intent.tools.base import BaseTool
from bot.intent.tools.chat import ChatTool
from bot.intent.tools.remind import RemindTool
from bot.intent.tools.task import TaskTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {
            ChatTool.name: ChatTool(),
            RemindTool.name: RemindTool(),
            TaskTool.name: TaskTool(),
        }

    @property
    def tools(self) -> dict[str, BaseTool]:
        return self._tools.copy()

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def register(self, name: str, tool: BaseTool) -> None:
        self._tools[name] = tool
