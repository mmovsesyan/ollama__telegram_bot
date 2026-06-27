import pytest
from unittest.mock import AsyncMock, patch

from bot.intent.router import LLMIntentRouter
from bot.ollama.dto import OllamaErrorChunk


class _FakeAsyncIterator:
    def __init__(self, items):
        self._items = list(items)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


class _FailingAsyncIterator:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise RuntimeError("generation failed")


class TestLLMIntentRouter:
    @pytest.fixture(autouse=True)
    def mock_context_builder(self):
        with patch(
            "bot.intent.router.ContextBuilder.build",
            new_callable=AsyncMock,
            return_value={},
        ) as mock:
            yield mock

    def _make_chunk(self, content: str):
        return type(
            "Chunk",
            (object,),
            {"message": type("Message", (object,), {"content": content})},
        )

    @pytest.mark.asyncio
    async def test_router_parses_json_response(self):
        fake_chunk = self._make_chunk(
            '{"intent":"create_reminder","tool":"remind","args":{"content":"test"},"confidence":0.95}'
        )

        # Use a free-form message without keyword triggers so the regex
        # fast-path doesn't intercept and the LLM mock actually runs.
        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ) as mock_gen:
            result = await LLMIntentRouter.route(user_id=1, message_text="abstract input")

        assert result.intent == "create_reminder"
        assert result.tool == "remind"
        assert result.confidence == 0.95
        assert result.args.content == "test"
        assert mock_gen.called

    @pytest.mark.asyncio
    async def test_router_parses_markdown_json(self):
        content = '```json\n{"intent":"chat","tool":"chat","args":{"content":"hello"},"confidence":0.9}\n```'
        fake_chunk = self._make_chunk(content)

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ) as mock_gen:
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.confidence == 0.9
        assert result.args.content == "hello"
        assert mock_gen.called

    @pytest.mark.asyncio
    async def test_router_parses_json_with_extra_text(self):
        content = 'Here is the intent: {"intent":"chat","tool":"chat","args":{},"confidence":0.85} Thanks!'
        fake_chunk = self._make_chunk(content)

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ) as mock_gen:
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.confidence == 0.85
        assert mock_gen.called

    @pytest.mark.asyncio
    async def test_router_parses_nested_braces(self):
        content = '{"intent":"chat","tool":"chat","args":{"content":"{nested}"},"confidence":0.9}'
        fake_chunk = self._make_chunk(content)

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello {nested}")

        assert result.intent == "chat"
        assert result.args.content == "{nested}"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_invalid_json(self):
        fake_chunk = self._make_chunk("not json")

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ) as mock_gen:
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"
        assert mock_gen.called

    @pytest.mark.asyncio
    async def test_router_falls_back_on_empty_response(self):
        fake_chunk = self._make_chunk("")

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_ollama_error_chunk(self):
        error_chunk = OllamaErrorChunk(error="model unavailable")

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, error_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_generation_exception(self):
        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FailingAsyncIterator(),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_invalid_intent(self):
        fake_chunk = self._make_chunk(
            '{"intent":"not_allowed","tool":"chat","args":{},"confidence":0.9}'
        )

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_invalid_tool(self):
        fake_chunk = self._make_chunk(
            '{"intent":"chat","tool":"not_allowed","args":{},"confidence":0.9}'
        )

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_missing_tool(self):
        fake_chunk = self._make_chunk(
            '{"intent":"chat","args":{},"confidence":0.9}'
        )

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_high_confidence(self):
        fake_chunk = self._make_chunk(
            '{"intent":"chat","tool":"chat","args":{},"confidence":1.5}'
        )

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_negative_confidence(self):
        fake_chunk = self._make_chunk(
            '{"intent":"chat","tool":"chat","args":{},"confidence":-0.1}'
        )

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_falls_back_on_missing_intent(self):
        fake_chunk = self._make_chunk(
            '{"tool":"chat","args":{},"confidence":0.9}'
        )

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.tool == "chat"  # fallback: regex finds no keyword in "hello", returns chat
        assert result.args.content == "hello"

    @pytest.mark.asyncio
    async def test_router_extracts_json_after_explanatory_braces(self):
        content = 'Note: {not json} Final intent: {"intent":"chat","tool":"chat","args":{},"confidence":0.88}'
        fake_chunk = self._make_chunk(content)

        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([(False, fake_chunk)]),
        ):
            result = await LLMIntentRouter.route(user_id=1, message_text="hello")

        assert result.intent == "chat"
        assert result.tool == "chat"
        assert result.confidence == 0.88

    @pytest.mark.asyncio
    async def test_topic_fast_path_routes_short_subject_to_news(self):
        for text in ("игры", "Tesla", "ai", "биткоин", "игровые"):
            result = await LLMIntentRouter.route(user_id=1, message_text=text)
            assert result.intent == "news", f"{text!r} should route to news"
            assert result.tool == "news"
            assert result.args.query == text

    @pytest.mark.asyncio
    async def test_topic_fast_path_skips_llm_call(self):
        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator([]),
        ) as mock_gen:
            result = await LLMIntentRouter.route(user_id=1, message_text="игры")

        assert result.intent == "news"
        assert result.tool == "news"
        assert not mock_gen.called

    @pytest.mark.asyncio
    async def test_topic_fast_path_yields_to_command_words(self):
        """Explicit commands like 'покажи игры' should not be forced to news."""
        with patch(
            "bot.intent.router.generate_chat_completion",
            return_value=_FakeAsyncIterator(
                [(False, self._make_chunk('{"intent":"news","tool":"news","args":{"query":"игры"},"confidence":0.9}'))]
            ),
        ) as mock_gen:
            result = await LLMIntentRouter.route(user_id=1, message_text="покажи игры")

        # The LLM was consulted because a command word is present.
        assert mock_gen.called
        assert result.intent == "news"
        assert result.tool == "news"
