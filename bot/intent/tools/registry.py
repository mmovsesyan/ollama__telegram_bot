from bot.intent.tools.base import BaseTool
from bot.intent.tools.chat import ChatTool
from bot.intent.tools.persistence import MemoryTool, MonitorTool, NoteTool, PlanTool
from bot.intent.tools.remind import RemindTool
from bot.intent.tools.search import NewsTool, SearchTool
from bot.intent.tools.task import TaskTool
from bot.intent.tools.weather import WeatherTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {
            ChatTool.name: ChatTool(),
            RemindTool.name: RemindTool(),
            TaskTool.name: TaskTool(),
            WeatherTool.name: WeatherTool(),
            SearchTool.name: SearchTool(),
            NewsTool.name: NewsTool(),
            NoteTool.name: NoteTool(),
            MemoryTool.name: MemoryTool(),
            MonitorTool.name: MonitorTool(),
            PlanTool.name: PlanTool(),
        }

    @property
    def tools(self) -> dict[str, BaseTool]:
        return self._tools.copy()

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def register(self, name: str, tool: BaseTool) -> None:
        self._tools[name] = tool
