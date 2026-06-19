"""Evening digest builder and sender.

Collects today's reminders/tasks, tomorrow's schedule, fresh news by user
categories, new memories/notes from today, and a short LLM-powered daily
takeaway. Sent automatically at a user-configured time (default 20:00).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.services import briefing as briefing_service
from bot.services.profile import get_zoneinfo, local_to_utc, now_in_tz, utc_to_local
from bot.settings import OLLAMA_MODEL

logger = logging.getLogger(__name__)

db = None  # injected at startup by bot.__init__

DEFAULT_DIGEST_TIME = "20:00"


def _user_prefs(user_id: int) -> dict:
    """User prefs shortcut; empty dict if DB unavailable."""
    if db is None:
        return {}
    try:
        return db.get_user_prefs(user_id) or {}
    except Exception:
        return {}


def _user_tz_name(user_id: int) -> str | None:
    return _user_prefs(user_id).get("timezone")


def _today_local(user_id: int) -> datetime:
    return now_in_tz(_user_tz_name(user_id))


def _date_window_local(user_id: int, day_offset: int) -> tuple[datetime, datetime]:
    """Return local start/end of today + offset as naive datetimes."""
    base = _today_local(user_id) + timedelta(days=day_offset)
    start = base.replace(hour=0, minute=0, second=0, microsecond=0)
    end = base.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


def _reminders_in_window(user_id: int, day_offset: int) -> tuple[list[dict], list[dict]]:
    """Return (reminders, tasks) scheduled in a local day window."""
    if db is None:
        return [], []
    tz_name = _user_tz_name(user_id)
    start_local, end_local = _date_window_local(user_id, day_offset)
    start_utc = local_to_utc(start_local, tz_name)
    end_utc = local_to_utc(end_local, tz_name)

    all_reminders = db.get_user_reminders(user_id)
    today = []
    for r in all_reminders:
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
        lines.append("🤖 Задачи:")
        for t in tasks:
            lines.append(_format_reminder_line(t, user_id))
    if not lines:
        return "Ничего не запланировано."
    return "\n".join(lines)


def _todays_memories(user_id: int) -> list[dict]:
    """Return memories created today in the user's timezone."""
    if db is None:
        return []
    tz_name = _user_tz_name(user_id)
    start_local, end_local = _date_window_local(user_id, 0)
    start_utc = local_to_utc(start_local, tz_name)
    end_utc = local_to_utc(end_local, tz_name)
    return db.get_memories_for_date(user_id, start_utc.isoformat(), end_utc.isoformat())


def _format_memories_block(memories: list[dict]) -> str:
    if not memories:
        return "Ничего нового не сохранено."
    lines = [m.get("content", "") for m in memories[:5] if m.get("content")]
    if not lines:
        return "Ничего нового не сохранено."
    return "\n".join(f"• {line}" for line in lines)


def _format_notes_block(notes: str | None) -> str:
    if not notes:
        return ""
    stripped = notes.strip()
    if not stripped:
        return ""
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(f"• {line.lstrip('- ')}" for line in lines[-5:])


async def _build_digest_advice(
    today_reminders: list[dict],
    today_tasks: list[dict],
    tomorrow_reminders: list[dict],
    tomorrow_tasks: list[dict],
    new_memories: list[dict],
) -> str:
    """Ask the local LLM for a short daily takeaway based on digest content."""
    model = OLLAMA_MODEL
    context_parts: list[str] = []

    if today_reminders or today_tasks:
        context_parts.append(
            "Сегодня запланировано: "
            + ", ".join(r.get("content", "") for r in today_reminders + today_tasks if r.get("content"))
        )
    if tomorrow_reminders or tomorrow_tasks:
        context_parts.append(
            "Завтра запланировано: "
            + ", ".join(r.get("content", "") for r in tomorrow_reminders + tomorrow_tasks if r.get("content"))
        )
    if new_memories:
        context_parts.append(
            "Новые факты: "
            + ", ".join(m.get("content", "") for m in new_memories if m.get("content"))
        )

    if not context_parts:
        return "Отдыхай — сегодня ничего не запланировано."

    prompt = (
        "Ты — личный ассистент. На основе данных пользователя за день напиши "
        "1–2 коротких предложения: краткий итог дня и мягкий совет/фокус на завтра. "
        "Без воды, по существу, на русском языке.\n\n"
        + "\n".join(context_parts)
    )

    messages = [OllamaChatMessage(role="user", content=prompt)]
    output = ""
    try:
        async with asyncio.timeout(60):
            async for is_done, chunk in generate_chat_completion(messages, model, temperature=0.5):
                if is_done:
                    break
                if isinstance(chunk, OllamaErrorChunk):
                    logger.warning("[DIGEST] LLM error: %s", chunk.error)
                    return ""
                output += chunk.message.content
    except asyncio.TimeoutError:
        logger.info("[DIGEST] advice generation timed out")
    except Exception as e:
        logger.warning("[DIGEST] advice generation failed: %s", e)
    return output.strip()


async def build_digest(user_id: int) -> str:
    """Compose the evening digest text for a user."""
    today_reminders, today_tasks = _reminders_in_window(user_id, 0)
    tomorrow_reminders, tomorrow_tasks = _reminders_in_window(user_id, 1)
    new_memories = _todays_memories(user_id)

    prefs = _user_prefs(user_id)
    notes = prefs.get("notes")

    today_block = _format_reminders_block(today_reminders, today_tasks, user_id)
    tomorrow_block = _format_reminders_block(tomorrow_reminders, tomorrow_tasks, user_id)
    memories_block = _format_memories_block(new_memories)
    notes_block = _format_notes_block(notes)

    news_block = await briefing_service._get_news_text(user_id, limit_per_category=2)
    advice = await _build_digest_advice(
        today_reminders,
        today_tasks,
        tomorrow_reminders,
        tomorrow_tasks,
        new_memories,
    ) or "Отдыхай — сегодня ничего не запланировано."

    parts = [
        "🌙 Добрый вечер! Вот сводка за день",
        "",
        f"📅 Сегодня\n{today_block}",
        "",
        f"🔮 Завтра\n{tomorrow_block}",
        "",
        f"📰 Новости\n{news_block}",
        "",
    ]
    if notes_block:
        parts.extend([f"📝 Заметки\n{notes_block}", ""])
    parts.extend(
        [
            f"🧠 Новое в памяти\n{memories_block}",
            "",
            f"💡 Итог дня\n{advice}",
        ]
    )
    return "\n".join(parts)[:4096]


async def send_digest(user_id: int, bot) -> None:
    """Build and send the digest, swallowing errors so the scheduler stays alive."""
    try:
        text = await build_digest(user_id)
    except Exception as e:
        logger.exception("[DIGEST] build failed for %s: %s", user_id, e)
        text = "Не удалось собрать вечерний дайджест. Попробую позже."
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.warning("[DIGEST] send failed for %s: %s", user_id, e)
