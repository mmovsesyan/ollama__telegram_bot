import pytest

from bot.intent.context import ContextBuilder


class _FakeDb:
    def __init__(
        self,
        prefs=None,
        session_id=10,
        summary=None,
        messages=None,
        memories=None,
    ):
        self._prefs = prefs or {}
        self._session_id = session_id
        self._summary = summary
        self._messages = messages or []
        self._memories = memories or []

    def get_user_prefs(self, user_id):
        return self._prefs

    def get_or_create_active_session(self, user_id, model):
        return self._session_id

    def get_latest_summary(self, session_id):
        return self._summary

    def get_session_messages(self, user_id, limit):
        return self._messages

    def search_memories(self, user_id, query, limit):
        return self._memories[:limit]


class TestContextBuilder:
    @pytest.fixture(autouse=True)
    def reset_db(self):
        ContextBuilder.db = None
        yield
        ContextBuilder.db = None

    @pytest.mark.asyncio
    async def test_build_returns_context_dict(self):
        ctx = await ContextBuilder.build(user_id=1, message_text="hello")
        assert ctx["user_id"] == 1
        assert ctx["message_text"] == "hello"
        assert "current_time" in ctx
        assert ctx["dialogue_summary"] == ""
        assert ctx["relevant_memory"] == []

    @pytest.mark.asyncio
    async def test_build_uses_db_profile(self):
        ContextBuilder.db = _FakeDb(
            prefs={
                "timezone": "Europe/Moscow",
                "language": "ru",
                "style": "verbose",
                "name": "Алекс",
            }
        )
        ctx = await ContextBuilder.build(user_id=1, message_text="hi")
        assert ctx["user_profile"]["timezone"] == "Europe/Moscow"
        assert ctx["user_profile"]["name"] == "Алекс"

    @pytest.mark.asyncio
    async def test_build_includes_session_summary(self):
        ContextBuilder.db = _FakeDb(summary={"summary": "User likes Python."})
        ctx = await ContextBuilder.build(user_id=1, message_text="hi")
        assert ctx["dialogue_summary"] == "User likes Python."

    @pytest.mark.asyncio
    async def test_build_includes_recent_messages(self):
        messages = [
            {"role": "user", "content": f"msg {i}"} for i in range(10)
        ]
        ContextBuilder.db = _FakeDb(messages=messages)
        ctx = await ContextBuilder.build(user_id=1, message_text="hi")
        # Only last 6 kept and content capped at 500 chars
        assert len(ctx["recent_messages"]) == 6
        assert ctx["recent_messages"][0]["content"] == "msg 4"
        assert ctx["recent_messages"][-1]["content"] == "msg 9"

    @pytest.mark.asyncio
    async def test_build_recent_messages_capped_at_500(self):
        long_msg = "x" * 600
        ContextBuilder.db = _FakeDb(messages=[{"role": "user", "content": long_msg}])
        ctx = await ContextBuilder.build(user_id=1, message_text="hi")
        assert len(ctx["recent_messages"][0]["content"]) == 500

    @pytest.mark.asyncio
    async def test_build_searches_memories_after_stripping_prefix(self):
        memories = [
            {"category": "fact", "summary": "Пользователь любит Python", "content": "..."}
        ]
        captured_queries = []

        class _Db(_FakeDb):
            def search_memories(self, user_id, query, limit):
                captured_queries.append(query)
                return memories

        ContextBuilder.db = _Db()
        ctx = await ContextBuilder.build(user_id=1, message_text="что я говорил про Python")
        assert captured_queries == ["Python"]
        assert len(ctx["relevant_memory"]) == 1
        assert ctx["relevant_memory"][0]["category"] == "fact"
        assert "Python" in ctx["relevant_memory"][0]["content"]

    @pytest.mark.asyncio
    async def test_build_survives_db_exceptions(self):
        class _BrokenDb:
            def get_user_prefs(self, user_id):
                raise RuntimeError("boom")

        ContextBuilder.db = _BrokenDb()
        ctx = await ContextBuilder.build(user_id=1, message_text="hi")
        assert ctx["user_profile"]["timezone"] == "UTC"
        assert ctx["recent_messages"] == []
