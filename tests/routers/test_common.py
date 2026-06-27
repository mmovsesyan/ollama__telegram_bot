import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

if "bot.bot" not in sys.modules:
    _fake_bot_module = types.ModuleType("bot.bot")
    _fake_bot_module.bot = MagicMock()
    sys.modules["bot.bot"] = _fake_bot_module

from bot.routers import common as common_module


@pytest.fixture(autouse=True)
def reset_bot():
    common_module.aiogram_bot = MagicMock()
    common_module.aiogram_bot.send_chat_action = AsyncMock()
    yield
    common_module.aiogram_bot = MagicMock()
    common_module.aiogram_bot.send_chat_action = AsyncMock()


@pytest.mark.asyncio
async def test_typing_until_cancels_worker_on_fast_task():
    import asyncio

    async def fast():
        await asyncio.sleep(0.1)
        return "done"



@pytest.mark.asyncio
async def test_typing_until_cancels_worker_on_exception():
    import asyncio

    async def boom():
        await asyncio.sleep(0.05)
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError, match="fail"):
        await common_module._typing_until(42, boom(), interval=0.01)
    assert common_module.aiogram_bot.send_chat_action.await_count >= 1
