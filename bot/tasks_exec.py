"""Compatibility shim for smart task execution.

The original `execute_smart()` lived here and routed on keywords. Its behavior
is now provided by the intent pipeline (``WeatherTool`` in
``bot/intent/tools/weather.py``) so this module only re-exports a thin wrapper
for the scheduler's reminder execution path.
"""

from bot.intent.schemas import IntentArgs, IntentResult, ToolContext
from bot.intent.tools.weather import WeatherTool


async def execute_smart(content: str) -> str | None:
    """Detect simple actionable intents and call real APIs if possible.

    Returns a result string when handled, or ``None`` to fall back to the
    generic LLM completion path.
    """
    text = (content or "").strip()
    if not text:
        return None

    lowered = text.lower()
    weather_indicators = {"погода", "weather", "температура", "прогноз погоды"}
    if any(w in lowered for w in weather_indicators):
        # Reuse the intent tool so behavior stays in one place.
        tool = WeatherTool()
        context = ToolContext(
            user_id=0,
            message_text=text,
            args=IntentArgs(query=text),
            intent_result=IntentResult(
                intent="weather",
                tool="weather",
                args=IntentArgs(query=text),
                confidence=1.0,
            ),
        )
        result = await tool.execute(context)
        if result.success:
            return result.text
        return result.text or "❌ Не удалось получить погоду"

    return None
