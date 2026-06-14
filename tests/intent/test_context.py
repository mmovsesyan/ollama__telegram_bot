import pytest
from bot.intent.context import ContextBuilder


class TestContextBuilder:
    @pytest.mark.asyncio
    async def test_build_returns_context_dict(self):
        ctx = await ContextBuilder.build(user_id=1, message_text="hello")
        assert ctx["user_id"] == 1
        assert ctx["message_text"] == "hello"
        assert "current_time" in ctx
        assert ctx["dialogue_summary"] == ""
        assert ctx["relevant_memory"] == []
