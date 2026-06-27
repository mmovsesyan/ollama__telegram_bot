from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.db import Database
from bot.routers import settings as settings_module


def _message(user_id: int = 42, text: str = ""):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _callback(user_id: int = 42, data: str = ""):
    cb = MagicMock()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.data = data
    cb.message = MagicMock()
    cb.message.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.answer = AsyncMock()
    return cb


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    settings_module.db = db
    yield db
    settings_module.db = None


@pytest.fixture(autouse=True)
def reset_state():
    settings_module.db = None
    yield
    settings_module.db = None


def test_bool_label():
    assert settings_module._bool_label(1) == "включено"
    assert settings_module._bool_label(0) == "выключено"
    assert settings_module._bool_label(True) == "включено"


def test_settings_text_defaults():
    prefs = {}
    text = settings_module._settings_text(prefs)
    assert "08:00" in text
    assert "tech,markets,ai" in text
    assert "Москва" in text  # default city for UTC


def test_settings_text_reflects_values():
    prefs = {
        "briefing_enabled": 0,
        "briefing_time": "09:30",
        "news_categories": "science",
        "briefing_city": "Ереван",
        "proactive_enabled": 1,
    }
    text = settings_module._settings_text(prefs)
    assert "выключено" in text
    assert "09:30" in text
    assert "science" in text
    assert "Ереван" in text


def test_ensure_prefs_creates_row(fresh_db):
    prefs = settings_module._user_prefs(42)
    assert prefs["user_id"] == 42
    assert prefs["briefing_enabled"] == 1


@pytest.mark.asyncio
async def test_cmd_settings(fresh_db):
    msg = _message(text="/settings")
    state = MagicMock()
    state.clear = AsyncMock()
    await settings_module.cmd_settings(msg, state)
    msg.answer.assert_awaited_once()
    text = msg.answer.await_args.args[0]
    assert "Настройки" in text


@pytest.mark.asyncio
async def test_toggle_briefing(fresh_db):
    fresh_db.set_user_prefs(42, briefing_enabled=1)
    cb = _callback(data="settings:toggle_briefing")
    await settings_module.cb_toggle_briefing(cb)
    prefs = fresh_db.get_user_prefs(42)
    assert prefs["briefing_enabled"] == 0
    cb.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_briefing_time_valid(fresh_db):
    msg = _message(text="09:15")
    state = MagicMock()
    state.clear = AsyncMock()
    await settings_module.process_briefing_time(msg, state)
    assert fresh_db.get_user_prefs(42)["briefing_time"] == "09:15"
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_briefing_time_invalid(fresh_db):
    msg = _message(text="25:00")
    state = MagicMock()
    state.clear = AsyncMock()
    fresh_db.set_user_prefs(42, timezone="UTC")
    await settings_module.process_briefing_time(msg, state)
    assert fresh_db.get_user_prefs(42)["briefing_time"] == "08:00"
    assert "Неверный формат" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_process_briefing_categories(fresh_db):
    msg = _message(text="tech, markets ,Crypto")
    state = MagicMock()
    state.clear = AsyncMock()
    await settings_module.process_briefing_categories(msg, state)
    cats = fresh_db.get_user_prefs(42)["news_categories"]
    assert cats == "tech,markets,crypto"


@pytest.mark.asyncio
async def test_process_briefing_city(fresh_db):
    msg = _message(text="Санкт-Петербург")
    state = MagicMock()
    state.clear = AsyncMock()
    await settings_module.process_briefing_city(msg, state)
    assert fresh_db.get_user_prefs(42)["briefing_city"] == "Санкт-Петербург"


def test_db_get_briefing_enabled_users(fresh_db):
    fresh_db.set_user_prefs(
        1, briefing_enabled=1, proactive_enabled=1, timezone="Europe/Moscow"
    )
    fresh_db.set_user_prefs(2, briefing_enabled=0, proactive_enabled=1, timezone="UTC")
    fresh_db.set_user_prefs(3, briefing_enabled=1, proactive_enabled=0, timezone="UTC")
    users = fresh_db.get_briefing_enabled_users()
    ids = {u["user_id"] for u in users}
    assert ids == {1}


def test_db_update_briefing_sent(fresh_db):
    fresh_db.set_user_prefs(42, briefing_enabled=1)
    fresh_db.update_briefing_sent(42, "2026-06-18")
    assert fresh_db.get_user_prefs(42)["last_briefing_date"] == "2026-06-18"
