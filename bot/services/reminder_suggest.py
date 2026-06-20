"""Smart proactive reminders, notes, and tasks from conversation context.

After enough messages have been exchanged (default 10) and a cooldown has
passed (default 5 minutes), the bot quietly asks an LLM to scan the recent
dialogue for commitments, ideas, or facts worth saving. High-confidence
suggestions (>= 0.7) are presented to the user with inline confirmation
buttons. Nothing is created without explicit user approval.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any

from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.settings import (
    OLLAMA_MODEL,
    SMART_REMINDERS_CONFIDENCE,
    SMART_REMINDERS_COOLDOWN_MIN,
    SMART_REMINDERS_ENABLED,
    SMART_REMINDERS_MESSAGE_THRESHOLD,
)

logger = logging.getLogger(__name__)

db: Any = None  # injected at startup by bot.__init__
reminders_service: Any = None  # injected at startup

# Per-user counters kept in memory. Restart resets them, which is acceptable
# for a best-effort proactive suggestion feature.
_state: dict[int, dict[str, Any]] = {}


def _user_state(user_id: int) -> dict[str, Any]:
    return _state.setdefault(user_id, {"message_count": 0, "last_suggestion_at": 0.0})


def record_interaction(user_id: int) -> None:
    """Call after each bot/user exchange to increment the message counter."""
    _user_state(user_id)["message_count"] += 1


def should_analyze(user_id: int) -> bool:
    """Return True when threshold messages are reached and cooldown passed."""
    if not SMART_REMINDERS_ENABLED:
        return False
    prefs = db.get_user_prefs(user_id) if db else {}
    if not (prefs or {}).get("smart_reminders_enabled", 1):
        return False
    state = _user_state(user_id)
    if state["message_count"] < SMART_REMINDERS_MESSAGE_THRESHOLD:
        return False
    cooldown_seconds = SMART_REMINDERS_COOLDOWN_MIN * 60
    if time.time() - state["last_suggestion_at"] < cooldown_seconds:
        return False
    return True


def _build_analysis_prompt(user_id: int) -> str:
    """Build a prompt that asks the LLM to find actionable items in recent chat."""
    messages: list[dict] = []
    if db is not None:
        try:
            raw = db.get_session_messages(user_id, limit=20)
            messages = [{"role": m["role"], "content": m["content"]} for m in raw]
        except Exception as exc:
            logger.warning(
                "Failed to load session messages for analysis %s: %s", user_id, exc
            )

    memories: list[str] = []
    if db is not None:
        try:
            for m in db.get_memories(user_id):
                content = (m.get("content") or "").strip()
                if content:
                    memories.append(content)
        except Exception as exc:
            logger.warning("Failed to load memories for analysis %s: %s", user_id, exc)

    reminders: list[str] = []
    if db is not None:
        try:
            for r in db.get_user_reminders(user_id):
                content = (r.get("content") or "").strip()
                if content:
                    reminders.append(content)
        except Exception as exc:
            logger.warning("Failed to load reminders for analysis %s: %s", user_id, exc)

    convo_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages[-10:])
    memory_text = "\n".join(f"- {m}" for m in memories)
    reminders_text = "\n".join(f"- {r}" for r in reminders)

    return (
        "Проанализируй последние сообщения диалога. Найди обязательства, встречи, "
        "идеи или факты, которые пользователь мог бы захотеть сохранить как "
        "напоминание, заметку или задачу.\n\n"
        "Верни JSON-массив (максимум 2 лучших предложения):\n"
        '[{"type": "reminder|note|task", "content": "краткое описание", '
        '"time": "когда выполнить (на русском, если известно)", '
        '"confidence": 0.0..1.0, "reason": "почему это важно"}]\n\n'
        "Правила:\n"
        f"- confidence должен быть >= {SMART_REMINDERS_CONFIDENCE} для worthy suggestions\n"
        "- не предлагай то, что уже есть в памяти или напоминаниях\n"
        "- content должен быть коротким и действительным\n"
        "- если ничего не нашёл — верни пустой массив []\n"
        "- отвечай ТОЛЬКО JSON, без markdown\n\n"
        f"ДИАЛОГ:\n{convo_text}\n\n"
        f"УЖЕ В ПАМЯТИ:\n{memory_text}\n\n"
        f"УЖЕ ЕСТЬ НАПОМИНАНИЯ:\n{reminders_text}\n\n"
        "ПРЕДЛОЖЕНИЯ:"
    )


def _extract_json(text: str) -> list[dict]:
    """Robustly pull the first JSON array out of the LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Find the first '[' that starts a balanced array.
    start = text.find("[")
    if start == -1:
        return []
    depth = 0
    end = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return []
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return []


def _is_duplicate(content: str, memories: list[str], reminders: list[str]) -> bool:
    """Check whether a suggestion semantically duplicates an existing item."""
    lowered = content.lower()
    for item in memories + reminders:
        if lowered in item.lower() or item.lower() in lowered:
            return True
    return False


async def analyze(user_id: int) -> list[dict]:
    """Run the LLM analysis and return high-confidence, deduplicated suggestions."""
    if db is None:
        return []

    prompt = _build_analysis_prompt(user_id)
    messages = [
        OllamaChatMessage(
            role="system", content="Ты анализируешь диалог и находишь важные моменты."
        ),
        OllamaChatMessage(role="user", content=prompt),
    ]
    raw = ""
    try:
        async with asyncio.timeout(30):
            async for is_done, chunk in generate_chat_completion(
                messages, OLLAMA_MODEL, temperature=0.3
            ):
                if is_done:
                    break
                if isinstance(chunk, OllamaErrorChunk):
                    logger.warning("[SMART_REMIND] LLM error: %s", chunk.error)
                    return []
                raw += chunk.message.content
    except asyncio.TimeoutError:
        logger.info("[SMART_REMIND] LLM timed out for user_id=%s", user_id)
        return []
    except Exception as e:
        logger.warning("[SMART_REMIND] LLM failed for user_id=%s: %s", user_id, e)
        return []

    suggestions = _extract_json(raw)
    if not isinstance(suggestions, list):
        return []

    memories: list[str] = []
    reminders: list[str] = []
    try:
        memories = [(m.get("content") or "").strip() for m in db.get_memories(user_id)]
        reminders = [
            (r.get("content") or "").strip() for r in db.get_user_reminders(user_id)
        ]
    except Exception as exc:
        logger.warning("Failed to load existing items for dedup %s: %s", user_id, exc)

    results = []
    for s in suggestions:
        try:
            if not isinstance(s, dict):
                continue
            confidence = float(s.get("confidence", 0))
            if confidence < SMART_REMINDERS_CONFIDENCE:
                continue
            content = (s.get("content") or "").strip()
            if not content:
                continue
            if _is_duplicate(content, memories, reminders):
                continue
            item_type = (s.get("type") or "note").lower()
            if item_type not in ("reminder", "note", "task"):
                item_type = "note"
            results.append(
                {
                    "type": item_type,
                    "content": content,
                    "time": (s.get("time") or "").strip(),
                    "confidence": confidence,
                    "reason": (s.get("reason") or "").strip(),
                }
            )
        except (TypeError, ValueError):
            continue
    return results[:2]


def _parse_time(time_text: str, user_id: int) -> tuple[str | None, str | None]:
    """Parse a human time expression into UTC ISO string + recurrence.

    Returns (trigger_at_iso, recurrence) or (None, None) on failure.
    """
    if not time_text or not reminders_service:
        return None, None
    tz_name = None
    if db is not None:
        try:
            prefs = db.get_user_prefs(user_id)
            tz_name = (prefs or {}).get("timezone")
        except Exception as exc:
            logger.warning(
                "Failed to load timezone for smart reminder %s: %s", user_id, exc
            )
    try:
        trigger_at, recurrence, parsed = reminders_service.parse_reminder_strict(
            time_text, tz_name=tz_name
        )
        if not parsed:
            return None, None
        return trigger_at.isoformat(), recurrence
    except Exception as e:
        logger.warning("[SMART_REMIND] time parse failed: %s", e)
        return None, None


def _escape_for_callback(text: str) -> str:
    """Encode suggestion content safely for aiogram callback data.

    aiogram callback_data has a 64-byte limit, so we truncate aggressively.
    """
    text = text.replace(":", " ").replace("|", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # UTF-8 bytes can exceed 64 bytes quickly; limit chars to keep under cap.
    return text[:40]


def suggestion_keyboard(suggestions: list[dict], user_id: int) -> Any:
    """Build an inline keyboard for confirming/dismissing smart suggestions."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for idx, s in enumerate(suggestions, 1):
        content = _escape_for_callback(s["content"])
        time_text = _escape_for_callback(s["time"])
        prefix = s["type"]
        data = f"suggest:{prefix}:{idx}:{content}:{time_text}"
        if len(data.encode("utf-8")) > 60:
            data = f"suggest:{prefix}:{idx}:{content[:20]}:{time_text[:10]}"
        label = f"{idx}. "
        if prefix == "reminder":
            label += "⏰ Напомнить"
        elif prefix == "task":
            label += "📋 Задача"
        else:
            label += "📝 Заметка"
        rows.append([InlineKeyboardButton(text=label, callback_data=data)])
    rows.append(
        [InlineKeyboardButton(text="❌ Не надо", callback_data="suggest:dismiss")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def suggestion_text(suggestions: list[dict]) -> str:
    lines = ["🤔 Возможно, стоит сохранить:"]
    for idx, s in enumerate(suggestions, 1):
        emoji = {"reminder": "⏰", "task": "📋", "note": "📝"}.get(s["type"], "📝")
        reason = s.get("reason")
        line = f"{idx}. {emoji} {s['content']}"
        if s.get("time"):
            line += f" (время: {s['time']})"
        if reason:
            line += f"\n   _{reason}_"
        lines.append(line)
    return "\n".join(lines)


async def create_reminder(user_id: int, content: str, time_text: str) -> str:
    """Create a reminder from a smart suggestion. Returns a status message."""
    if db is None:
        return "⚠️ База данных недоступна."
    trigger_at, recurrence = _parse_time(time_text, user_id)
    if trigger_at is None:
        return (
            f"⚠️ Не удалось понять время для напоминания «{content}».\n"
            "Попробуй создать вручную: /remind"
        )
    db.add_reminder(
        user_id=user_id,
        content=content,
        trigger_at=trigger_at,
        recurring=recurrence,
        action="notify",
    )
    return f"✅ Напоминание добавлено:\n📝 {content}\n🕐 {time_text or 'скоро'}"


async def create_task(user_id: int, content: str, time_text: str) -> str:
    """Create an AI-executed task from a smart suggestion."""
    if db is None:
        return "⚠️ База данных недоступна."
    trigger_at, recurrence = _parse_time(time_text, user_id)
    if trigger_at is None:
        return (
            f"⚠️ Не удалось понять время для задачи «{content}».\n"
            "Попробуй создать вручную: /task"
        )
    db.add_reminder(
        user_id=user_id,
        content=content,
        trigger_at=trigger_at,
        recurring=recurrence,
        action="execute",
    )
    return f"✅ Задача добавлена:\n📝 {content}\n🕐 {time_text or 'скоро'}"


async def create_note(user_id: int, content: str) -> str:
    """Save a note from a smart suggestion."""
    if db is None:
        return "⚠️ База данных недоступна."
    db.add_note(user_id, content)
    try:
        from bot.routers import completion

        completion.refresh_system_prompt(user_id)
    except Exception as exc:
        logger.warning(
            "Failed to refresh system prompt after note save %s: %s", user_id, exc
        )
    return f"✅ Заметка сохранена:\n📝 {content}"


async def analyze_and_suggest(user_id: int, send_message) -> None:
    """Background entry point: analyze and send suggestions if any."""
    if not should_analyze(user_id):
        return

    # Reset counter immediately so we don't retry on failure/empty results.
    state = _user_state(user_id)
    state["message_count"] = 0
    state["last_suggestion_at"] = time.time()

    suggestions = await analyze(user_id)
    if not suggestions:
        return

    text = suggestion_text(suggestions)
    keyboard = suggestion_keyboard(suggestions, user_id)
    await send_message(text, reply_markup=keyboard)
