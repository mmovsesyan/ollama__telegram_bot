import asyncio
from unittest.mock import patch

import pytest

from bot.ollama import OllamaChatMessage
from bot.ollama.api import generate_chat_completion


def _make_chunk(content: str, done: bool = False) -> dict:
    return {
        "created_at": "2024-01-01T00:00:00Z",
        "model": "m",
        "done": done,
        "message": {"role": "assistant", "content": content},
    }


@pytest.mark.asyncio
async def test_semaphore_serializes_calls_when_limit_one():
    order = []

    async def slow_gen(*args, **kwargs):
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")
        yield _make_chunk("ok", done=True)

    with patch("bot.ollama.api.ollama_semaphore", asyncio.Semaphore(1)):
        with patch("bot.ollama.api._stream_ollama_chat", side_effect=slow_gen):
            with patch("bot.ollama.api._stream_openai_chat", side_effect=slow_gen):
                async def run():
                    async for _ in generate_chat_completion([OllamaChatMessage(role="user", content="a")], "m"):
                        pass

                await asyncio.gather(run(), run())

    assert order == ["start", "end", "start", "end"]


@pytest.mark.asyncio
async def test_semaphore_allows_parallel_calls_when_limit_two():
    order = []

    async def slow_gen(*args, **kwargs):
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")
        yield _make_chunk("ok", done=True)

    with patch("bot.ollama.api.ollama_semaphore", asyncio.Semaphore(2)):
        with patch("bot.ollama.api._stream_ollama_chat", side_effect=slow_gen):
            with patch("bot.ollama.api._stream_openai_chat", side_effect=slow_gen):
                async def run():
                    async for _ in generate_chat_completion([OllamaChatMessage(role="user", content="a")], "m"):
                        pass

                await asyncio.gather(run(), run())

    assert order.count("start") == 2
    assert order.count("end") == 2
    # Both started before any ended → overlapping.
    assert order.index("end") > order.index("start", 1)
