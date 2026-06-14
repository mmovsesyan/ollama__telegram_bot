from abc import ABC, abstractmethod
from bot.intent.schemas import ToolContext, ToolResult


class BaseTool(ABC):
    name: str
    required_args: tuple[str, ...] = ()

    @abstractmethod
    async def execute(self, context: ToolContext) -> ToolResult: ...
