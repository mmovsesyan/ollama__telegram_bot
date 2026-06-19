"""Detect when the user reports completing a task/reminder and offer to close it.

Users often reply with short updates like «сделал», «готово», or «завершил».
When the text also references an active reminder, the bot offers a single-tap
button to disable the reminder instead of forcing the user to hunt /reminders.
"""

import logging
import re
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

db: Any = None  # injected at startup by bot.__init__


_COMPLETION_KEYWORDS_RE = re.compile(
    r"\b("
    r"сделал[аои]?|"
    r"сделано|"
    r"готово|готова|готовы|"
    r"выполнил[аои]?|выполнено|"
    r"завершил[аои]?|завершено|"
    r"закрыл[аои]?|закрыто|"
    r"отменил[аои]?|отменено|"
    r"не\s+актуально|"
    r"done|completed|finished|did\s+it|"
    r"ready|"
    r"вышло|"
    r"получилось"
    r")\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Lowercase and strip punctuation for overlap comparisons."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _tokenize(text: str) -> set[str]:
    """Return meaningful word tokens, dropping very short words."""
    return {w for w in _normalize(text).split() if len(w) > 2}


def looks_like_completion(text: str) -> bool:
    """Return True if the user text sounds like a completion report."""
    return bool(_COMPLETION_KEYWORDS_RE.search(text))


def _score_match(user_text: str, reminder_content: str) -> float:
    """Return overlap score between user text and reminder content.

    Score is the share of reminder content tokens that appear in the user text.
    """
    user_tokens = _tokenize(user_text)
    reminder_tokens = _tokenize(reminder_content)
    if not reminder_tokens:
        return 0.0
    matches = reminder_tokens & user_tokens
    return len(matches) / len(reminder_tokens)


_MIN_MATCH_SCORE = 0.5
_MIN_OVERLAP_TOKENS = 2


def find_matching_reminder(user_id: int, text: str) -> dict | None:
    """Find an active reminder whose content matches the user's completion text.

    Returns the best-matching enabled reminder, or None if no match is good enough.
    """
    if db is None:
        return None
    try:
        reminders = db.get_user_reminders(user_id)
    except Exception:
        logger.exception("[REMIND_COMP] failed to load reminders for user_id=%s", user_id)
        return None

    if not looks_like_completion(text):
        return None

    user_tokens = _tokenize(text)
    best: dict | None = None
    best_score = 0.0

    for reminder in reminders:
        content = reminder.get("content") or ""
        score = _score_match(text, content)
        overlap = len(_tokenize(text) & _tokenize(content))
        if overlap >= _MIN_OVERLAP_TOKENS and score >= _MIN_MATCH_SCORE and score > best_score:
            best = reminder
            best_score = score

    return best


def completion_offer_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Inline keyboard for confirming reminder completion."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, закрыть", callback_data=f"reminder_done:{reminder_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Нет", callback_data="reminder_done:dismiss"
                ),
            ],
        ]
    )


def completion_offer_text(user_text: str, reminder_content: str) -> str:
    """Build the confirmation message shown when a completion is detected."""
    return (
        f"Похоже, что задача «{reminder_content}» выполнена?\n"
        f"Ты написал: «{user_text}»\n\n"
        f"Закрыть напоминание?"
    )


def complete_reminder(user_id: int, reminder_id: int) -> str:
    """Disable/delete a reminder after user confirmation. Returns status text."""
    if db is None:
        return "⚠️ База данных недоступна."
    try:
        reminder = db.get_reminder(reminder_id)
        if not reminder or reminder.get("user_id") != user_id:
            return "⚠️ Напоминание не найдено или нет доступа."
        db.disable_reminder(reminder_id)
        content = reminder.get("content") or ""
        return f"✅ Закрыл напоминание: {content}"
    except Exception:
        logger.exception("[REMIND_COMP] failed to complete reminder_id=%s", reminder_id)
        return "⚠️ Не удалось закрыть напоминание."


def maybe_offer_completion(user_id: int, text: str) -> tuple[str, InlineKeyboardMarkup] | None:
    """If the text completes an active reminder, return (message, keyboard)."""
    reminder = find_matching_reminder(user_id, text)
    if reminder is None:
        return None
    reminder_id = reminder.get("id")
    if reminder_id is None:
        return None
    content = reminder.get("content") or ""
    return completion_offer_text(text, content), completion_offer_keyboard(reminder_id)
