from datetime import datetime, timezone


class ContextBuilder:
    @classmethod
    async def build(cls, user_id: int, message_text: str) -> dict:
        return {
            "user_id": user_id,
            "message_text": message_text,
            "user_profile": {"timezone": "UTC", "language": "ru", "summary_style": "short"},
            "dialogue_summary": "",
            "recent_messages": [],
            "relevant_memory": [],
            "active_state": {},
            "current_time": datetime.now(timezone.utc).isoformat(),
        }
