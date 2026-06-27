import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if "bot.bot" not in sys.modules:
    _fake_bot_module = ModuleType("bot.bot")
    _fake_bot_module.bot = MagicMock()
    sys.modules["bot.bot"] = _fake_bot_module

from bot.routers import admin_control as ac_module


def _message(user_id: int, text: str):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


@pytest.fixture(autouse=True)
def reset_admin_ids():
    # ADMIN_IDS is a module-level frozen set; each test patches it explicitly.
    yield


@pytest.mark.asyncio
async def test_bot_status_shown_to_admin():
    with patch.object(ac_module, "ADMIN_IDS", {42}):
        msg = _message(42, "/bot_status")
        state = MagicMock()
        state.clear = AsyncMock()
        await ac_module.cmd_bot_status(msg, state)
        msg.answer.assert_awaited()
    # First message is the interim "Получаю статус..."; final text is the status.
    assert len(msg.answer.await_args_list) >= 1


@pytest.mark.asyncio
async def test_bot_status_hidden_from_non_admin():

    with patch.object(ac_module, "ADMIN_IDS", {42}):
        msg = _message(7, "/bot_status")
        state = MagicMock()
        state.clear = AsyncMock()
        await ac_module.cmd_bot_status(msg, state)
        msg.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot_start_calls_supervisor():
    with patch.object(ac_module, "ADMIN_IDS", {42}):
        with patch.object(ac_module.supervisor, "start", new=AsyncMock(return_value=(True, "ok"))):
            msg = _message(42, "/bot_start")
            state = MagicMock()
            state.clear = AsyncMock()
            await ac_module.cmd_bot_start(msg, state)
            # Interim message then final status edit.
            assert msg.answer.await_count == 1
            assert "Запускаю бота" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_bot_logs_returns_preformatted_text():
    with patch.object(ac_module, "ADMIN_IDS", {42}):
        with patch.object(ac_module.supervisor, "tail_logs", new=AsyncMock(return_value="<pre>log</pre>")):
            msg = _message(42, "/bot_logs")
            state = MagicMock()
            state.clear = AsyncMock()
            await ac_module.cmd_bot_logs(msg, state)
            args, kwargs = msg.answer.call_args
            assert args[0] == "<pre>log</pre>"
            assert kwargs.get("parse_mode") == "HTML"
