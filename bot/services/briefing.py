"""Morning briefing builder and sender.

Collects weather, today's reminders/tasks, fresh news by user categories,
and a memory-based tip, then composes a concise Telegram-friendly message.
"""

import logging
from datetime import datetime, timezone

from bot.services.profile import get_zoneinfo, local_to_utc, now_in_tz, utc_to_local

logger = logging.getLogger(__name__)

db = None  # injected at startup by bot.__init__

DEFAULT_BRIEFING_CITY = "Москва"
DEFAULT_CATEGORIES = "tech,markets,ai"

# Map common category slugs to Russian keywords that match the RSS corpus.
CATEGORY_TOPICS = {
    "tech": "технологии ИИ",
    "markets": "рынок акции финансы",
    "ai": "искусственный интеллект",
    "science": "наука",
    "crypto": "криптовалюта биткоин",
    "world": "мир",
}


def _user_prefs(user_id: int) -> dict:
    if db is None:
        return {}
    try:
        return db.get_user_prefs(user_id) or {}
    except Exception:
        return {}


def _user_tz_name(user_id: int) -> str | None:
    return _user_prefs(user_id).get("timezone")


def _default_city_for_tz(tz_name: str | None) -> str:
    if not tz_name:
        return DEFAULT_BRIEFING_CITY
    if "Moscow" in tz_name or "Kaliningrad" in tz_name:
        return "Москва"
    if "Yerevan" in tz_name or "Tbilisi" in tz_name or "Baku" in tz_name:
        return "Ереван"
    if "Almaty" in tz_name or "Tashkent" in tz_name:
        return "Алматы"
    if "Minsk" in tz_name or "Kyiv" in tz_name:
        return "Минск"
    if "London" in tz_name:
        return "Лондон"
    if "Paris" in tz_name or "Berlin" in tz_name or "Amsterdam" in tz_name:
        return "Берлин"
    if "New_York" in tz_name or "Toronto" in tz_name:
        return "Нью-Йорк"
    if "Sydney" in tz_name:
        return "Сидней"
    if "Tokyo" in tz_name:
        return "Токио"
    return DEFAULT_BRIEFING_CITY


def _user_city(user_id: int) -> str:
    prefs = _user_prefs(user_id)
    return prefs.get("briefing_city") or _default_city_for_tz(_user_tz_name(user_id))


def _today_local_iso(user_id: int) -> str:
    return now_in_tz(_user_tz_name(user_id)).strftime("%Y-%m-%d")


async def _get_weather_text(user_id: int) -> str:
    from bot.services.weather import get_weather

    city = _user_city(user_id)
    try:
        text, error = await get_weather(city)
        if text:
            return text
        return f"Погода недоступна: {error}"
    except Exception as e:
        logger.warning("[BRIEFING] weather failed for %s: %s", user_id, e)
        return "Погода временно недоступна"


def _todays_reminders(user_id: int) -> tuple[list[dict], list[dict]]:
    """Return (reminders, tasks) scheduled for today in the user's timezone."""
    if db is None:
        return [], []
    tz_name = _user_tz_name(user_id)
    now_local = now_in_tz(tz_name)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_utc = local_to_utc(start_local, tz_name)
    end_utc = local_to_utc(end_local, tz_name)

    reminders = db.get_user_reminders(user_id)
    today = []
    for r in reminders:
        if not r.get("enabled", 1):
            continue
        trigger_at = r.get("trigger_at")
        if not trigger_at:
            continue
        if start_utc.isoformat() <= trigger_at <= end_utc.isoformat():
            today.append(r)

    reminders_list = [r for r in today if r.get("action", "notify") != "execute"]
    tasks_list = [r for r in today if r.get("action", "notify") == "execute"]
    return reminders_list, tasks_list


def _format_reminder_line(r: dict, user_id: int) -> str:
    tz_name = _user_tz_name(user_id)
    trigger = r.get("trigger_at")
    try:
        dt_utc = datetime.fromisoformat(trigger)
        dt_local = utc_to_local(dt_utc, tz_name)
        time_str = dt_local.strftime("%H:%M")
    except Exception:
        time_str = "ASAP"
    return f"{time_str}: {r.get('content', '')}"


def _format_reminders_block(reminders: list[dict], tasks: list[dict], user_id: int) -> str:
    lines: list[str] = []
    if reminders:
        lines.append("⏰ Напоминания:")
        for r in reminders:
            lines.append(_format_reminder_line(r, user_id))
    if tasks:
        lines.append("🤖 Задачи на сегодня:")
        for t in tasks:
            lines.append(_format_reminder_line(t, user_id))
    if not lines:
        return "Нет дел на сегодня."
    return "\n".join(lines)


async def _get_news_text(user_id: int, limit_per_category: int = 2) -> str:
    from bot.services import rss_news as rss_news_service

    prefs = _user_prefs(user_id)
    categories = (prefs.get("news_categories") or DEFAULT_CATEGORIES).split(",")
    blocks: list[str] = []
    for raw_cat in categories:
        cat = raw_cat.strip().lower()
        if not cat:
            continue
        topic = CATEGORY_TOPICS.get(cat, cat)
        try:
            text, _items, _source = await rss_news_service.get_fresh_news(
                user_id, topic=topic, limit=limit_per_category
            )
        except Exception as e:
            logger.warning("[BRIEFING] news for %s failed: %s", cat, e)
            continue
        if text:
            blocks.append(f"📌 {cat.upper()}\n{text}")
    if not blocks:
        return "Новостей по вашим темам сегодня не найдено."
    return "\n\n".join(blocks)


def _memory_advice(user_id: int) -> str:
    if db is None:
        return ""
    try:
        memories = db.get_memories(user_id)
    except Exception:
        return ""
    if not memories:
        return "Нет сохранённых фактов. Добавляй через /memory."
    recent = memories[:3]
    lines = [m.get("content", "") for m in recent]
    return "Вспомни:\n" + "\n".join(f"• {line}" for line in lines if line)


async def build_briefing(user_id: int) -> str:
    """Compose the morning briefing text for a user."""
    weather = await _get_weather_text(user_id)
    reminders, tasks = _todays_reminders(user_id)
    reminders_block = _format_reminders_block(reminders, tasks, user_id)
    news_block = await _get_news_text(user_id)
    advice = _memory_advice(user_id)

    parts = [
        "🌅 Доброе утро! Вот твой брифинг",
        "",
        f"🌤 Погода\n{weather}",
        "",
        f"⏰ Дела на сегодня\n{reminders_block}",
        "",
        f"📰 Новости\n{news_block}",
        "",
        f"💡 Вывод дня\n{advice}",
    ]
    return "\n".join(parts)[:4096]


async def send_briefing(user_id: int, bot) -> None:
    """Build and send the briefing, swallowing errors so the scheduler stays alive."""
    try:
        text = await build_briefing(user_id)
    except Exception as e:
        logger.exception("[BRIEFING] build failed for %s: %s", user_id, e)
        text = "Не удалось собрать утренний брифинг. Попробую позже."
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.warning("[BRIEFING] send failed for %s: %s", user_id, e)
