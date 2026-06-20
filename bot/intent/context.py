import logging
from datetime import datetime, timezone
from typing import Any

from bot.settings import MAX_CONTEXT_MESSAGES, OLLAMA_MODEL

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Build a rich context dict for the LLM intent router.

    Unlike the earlier stub, this implementation pulls the user's real
    profile, latest session summary, recent messages, and any memories that
    look relevant to the current message. This makes ambiguous free-form
    requests like "что я говорил про X" or "запомни это" route correctly.
    """

    db: Any = None  # injected at startup by bot.__init__

    @classmethod
    async def build(cls, user_id: int, message_text: str) -> dict:
        db = cls.db
        profile = {"timezone": "UTC", "language": "ru", "summary_style": "short"}
        dialogue_summary = ""
        recent_messages: list[dict] = []
        relevant_memory: list[dict] = []

        if db is not None:
            try:
                prefs = db.get_user_prefs(user_id)
                if prefs:
                    profile = {
                        "timezone": prefs.get("timezone") or "UTC",
                        "language": prefs.get("language") or "ru",
                        "summary_style": prefs.get("style") or "short",
                        "name": prefs.get("name") or None,
                    }
            except Exception as exc:
                logger.warning("Failed to load user prefs for %s: %s", user_id, exc)

            try:
                session_id = db.get_or_create_active_session(user_id, OLLAMA_MODEL)
                latest_summary = db.get_latest_summary(session_id)
                if latest_summary and latest_summary.get("summary"):
                    dialogue_summary = latest_summary["summary"]
            except Exception as exc:
                logger.warning(
                    "Failed to load session summary for %s: %s", user_id, exc
                )

            try:
                recent_messages = db.get_session_messages(
                    user_id, limit=MAX_CONTEXT_MESSAGES
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load session messages for %s: %s", user_id, exc
                )
                recent_messages = []

            try:
                query = message_text.strip()
                # Drop leading command-like words so search targets the subject.
                for prefix in (
                    "запомни ",
                    "запомни, ",
                    "факт ",
                    "факт: ",
                    "заметка ",
                    "заметка: ",
                    "напомни ",
                    "что я говорил про ",
                    "что у меня про ",
                    "найди у меня про ",
                    "найди в базе ",
                    "поищи в базе ",
                    "из моей базы ",
                    "в моей базе ",
                    "из базы ",
                ):
                    if query.lower().startswith(prefix):
                        query = query[len(prefix) :].strip()
                        break
                if query:
                    relevant_memory = db.search_memories(user_id, query, limit=5)
            except Exception as exc:
                logger.warning("Failed to search memories for %s: %s", user_id, exc)
                relevant_memory = []

        return {
            "user_id": user_id,
            "message_text": message_text,
            "user_profile": profile,
            "dialogue_summary": dialogue_summary,
            "recent_messages": [
                {"role": m["role"], "content": m["content"][:500]}
                for m in recent_messages[-6:]
            ],
            "relevant_memory": [
                {
                    "category": m.get("category", "fact"),
                    "content": (m.get("summary") or m.get("content", ""))[:300],
                }
                for m in relevant_memory
            ],
            "active_state": {},
            "current_time": datetime.now(timezone.utc).isoformat(),
        }
