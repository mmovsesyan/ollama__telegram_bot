"""Smart task execution: detect intent and call real APIs if possible."""

import re

from bot.services.weather import get_weather


def _extract_city(text: str) -> str | None:
    """Extract city name from weather-like query.

    Strips common keywords with word-boundary anchors so short prepositions
    ("в", "по", "для") don't bleed into multi-word city names like
    "Санкт-Петербург".
    """
    text = text.lower()
    # Anchored patterns — \b prevents stripping "в" from inside "Санкт-Петербурге"
    keywords = [
        r"\bпогода\b", r"\bпогоду\b", r"\bweather\b", r"\bтемпература\b",
        r"\bпрогноз(а|у)?\b", r"\bполная\b", r"\bтекущая\b", r"\bсейчас\b",
        r"\btoday\b", r"\bcurrent\b", r"\bдля\b", r"\bв\b", r"\bfor\b",
        r"\bin\b", r"\bпо\b", r"\bгород\b", r"\bcity\b", r"\bотправить\b",
        r"\bприслать\b", r"\bскажи\b", r"\bдай\b", r"\bузнать\b",
        r"\bактуальная\b", r"\bна\s+сегодня\b", r"\bна\s+завтра\b",
    ]
    cleaned = text
    for kw in keywords:
        cleaned = re.sub(kw, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^\w\s\-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    words = cleaned.split()
    if not words:
        return None
    return words[0].capitalize()


async def execute_smart(content: str) -> str | None:
    """Detect intent and call real APIs if possible.
    Returns result string if handled, None to fall back to generic LLM."""
    text_lower = content.lower()

    weather_indicators = ["погода", "weather", "температура", "прогноз погоды"]
    if any(w in text_lower for w in weather_indicators):
        city = _extract_city(content)
        if city:
            result, error = await get_weather(city)
            if result:
                return result
            if error:
                return f"❌ Ошибка погоды: {error}"
        return "❌ Укажите город для погоды. Пример: погода Москва"

    return None
