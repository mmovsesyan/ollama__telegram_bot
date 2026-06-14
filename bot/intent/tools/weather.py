from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.services.weather import get_weather


class WeatherTool(BaseTool):
    name = "weather"
    required_args = ("city",)

    async def execute(self, context: ToolContext) -> ToolResult:
        city = context.args.city or ""
        if not city.strip():
            return ToolResult(text="🌤 Какой город?", success=False)
        text, error = await get_weather(city.strip())
        if error or not text:
            return ToolResult(text=f"❌ Ошибка погоды: {error or 'нет данных'}", success=False)
        return ToolResult(text=text)
