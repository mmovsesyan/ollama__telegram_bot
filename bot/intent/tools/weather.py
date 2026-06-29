import re

from bot.intent.schemas import ToolContext, ToolResult
from bot.intent.tools.base import BaseTool
from bot.services.weather import get_forecast, get_weather


_FORECAST_PHRASE_RE = re.compile(
    r"прогноз|неделю|неделя|месяц|выходные|"
    r"(?<!\w)(?:на\s+)?завтра(?!\w)|послезавтра|"
    r"на\s+\d+\s*(?:день|дня|дней|сутки|суток)|"
    r"\d+\s*(?:день|дня|дней|сутки|суток)|"
    r"на\s+ближайш\w*|ближайш\w*\s+(?:неделю|месяц|дни|дней)|"
    r"forecast|next\s+\d+\s+days?|this\s+week|this\s+month|tomorrow",
    re.IGNORECASE,
)
_DAYS_RE = re.compile(
    r"(?:на\s+)?(\d{1,2})\s*(?:день|дня|дней|сутки|суток)|next\s+(\d{1,2})\s+days?",
    re.IGNORECASE,
)


def extract_city(text: str) -> str | None:
    """Pull the city out of weather queries like 'погода в Москве'."""
    if not text:
        return None
    weather_text = re.sub(
        r"\b(?:прогноз\w*\s+)?(?:погод\w*|weather|температур\w*|прогноз\w*|forecast)\b",
        "WX",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    m = re.search(
        r"WX\s*(?:в|in|для|по|for)?\s*([\wа-яА-ЯёЁ\-]+)?",
        weather_text,
    )
    if not m:
        return None
    city = (m.group(1) or "").strip()
    if city.lower() in {"на", "по", "для", "в", "с", "за", "и", "the", "a", "in", "for"}:
        return None
    return city.capitalize() or None


def _detect_days(text: str) -> int | None:
    """Pull a day-count out of phrases like 'на 5 дней', '3 дня', 'next 3 days'.
    Returns None if no explicit number was given."""
    if not text:
        return None
    m = _DAYS_RE.search(text)
    if m:
        n = int(m.group(1) or m.group(2))
        return max(1, min(n, 16))
    low = text.lower()
    # Open-Meteo caps daily forecast at 16 days, so 'месяц' rounds down.
    if "месяц" in low or "this month" in low:
        return 16
    if "недел" in low or "this week" in low:
        return 7
    if "выходные" in low:
        return 3
    if "послезавтра" in low:
        return 3
    if "завтра" in low or "tomorrow" in low:
        return 2
    return None


class WeatherTool(BaseTool):
    name = "weather"
    required_args = ("city",)

    async def execute(self, context: ToolContext) -> ToolResult:
        city = (context.args.city or "").strip()
        if not city:
            return ToolResult(text="🌤 Какой город?", success=False)

        days = context.args.days
        if days is None:
            days = _detect_days(context.args.query or "") or _detect_days(context.message_text or "")
        is_forecast = bool(days) or bool(_FORECAST_PHRASE_RE.search(context.message_text or ""))

        if is_forecast:
            text, error = await get_forecast(city, days or 7)
        else:
            text, error = await get_weather(city)
        if error or not text:
            return ToolResult(text=f"❌ Ошибка погоды: {error or 'нет данных'}", success=False)
        return ToolResult(text=text)
