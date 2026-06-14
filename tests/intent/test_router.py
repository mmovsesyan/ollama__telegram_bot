import pytest
from unittest.mock import AsyncMock, patch
from bot.intent.router import LLMIntentRouter


class TestLLMIntentRouter:
    @pytest.mark.asyncio
    async def test_router_parses_json_response(self):
        fake_chunk = type("Chunk", (object,), {
            "message": type("Message", (object,), {"content": '{"intent":"create_reminder","tool":"remind","args":{"content":"test"},"confidence":0.95}'}),
        })

        async def _fake_gen(*args, **kwargs):
            yield (False, fake_chunk)
            yield (True, None)

        with patch("bot.intent.router.generate_chat_completion", side_effect=_fake_gen) as mock_gen:
            result = await LLMIntentRouter.route(user_id=1, message_text="remind me to test")

        assert result.intent == "create_reminder"
        assert result.tool == "remind"
        assert result.confidence == 0.95
        assert result.args.content == "test"
        assert mock_gen.called

    @pytest.mark.asyncio
    async def test_router_falls_back_on_invalid_json(self):
        fake_chunk = type("Chunk", (object,), {
            "message": type("Message", (object,), {"content": "not json"}),
        })

        async def _fake_gen(*args, **kwargs):
            yield (False, fake_chunk)
            yield (True, None)

        with patch("bot.intent.router.generate_chat_completion", side_effect=_fake_gen) as mock_gen:
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.confidence == 0.0
        assert result.args.content == "hello"
        assert mock_gen.called
