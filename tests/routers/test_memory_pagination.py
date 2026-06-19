from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.db import Database
from bot.keyboards.inline import memory_filter_keyboard, memory_pagination_keyboard
from bot.routers import cron as cron_module


def _callback(user_id: int = 42, data: str = "memory_menu:show", message=None):
    cb = MagicMock()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.data = data
    cb.message = message
    cb.answer = AsyncMock()
    return cb


def _message_with_edit(user_id: int = 42):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = "stub"
    msg.answer = AsyncMock()
    msg.edit_text = AsyncMock()
    return msg


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    cron_module.db = db
    yield db
    cron_module.db = None


@pytest.fixture(autouse=True)
def reset_state():
    cron_module.db = None
    yield
    cron_module.db = None


@pytest.mark.asyncio
async def test_show_memories_paginates(fresh_db):
    for i in range(7):
        fresh_db.add_memory(42, "fact", f"memory content {i + 1}")

    msg = _message_with_edit()
    await cron_module._show_memories(42, msg, page=0, category="all")

    text = msg.answer.await_args.args[0]
    assert "#1" in text
    assert "#5" in text
    assert "#6" not in text


@pytest.mark.asyncio
async def test_show_memories_second_page(fresh_db):
    for i in range(7):
        fresh_db.add_memory(42, "fact", f"memory content {i + 1}")

    msg = _message_with_edit()
    await cron_module._show_memories(42, msg, page=1, category="all")

    text = msg.answer.await_args.args[0]
    assert "#6" in text
    assert "#7" in text
    assert "#1" not in text


@pytest.mark.asyncio
async def test_show_memories_filters_by_category(fresh_db):
    fresh_db.add_memory(42, "fact", "fact one")
    fresh_db.add_memory(42, "preference", "preference one")
    fresh_db.add_memory(42, "note", "note one")

    msg = _message_with_edit()
    await cron_module._show_memories(42, msg, page=0, category="preference")

    text = msg.answer.await_args.args[0]
    assert "preference one" in text
    assert "fact one" not in text
    assert "note one" not in text


@pytest.mark.asyncio
async def test_cb_memory_page_switches_page(fresh_db):
    for i in range(7):
        fresh_db.add_memory(42, "fact", f"memory content {i + 1}")

    msg = _message_with_edit()
    cb = _callback(data="mem_page:1:all", message=msg)

    await cron_module.cb_memory_page(cb)

    cb.answer.assert_awaited_once()
    text = msg.edit_text.await_args.args[0]
    assert "#6" in text


@pytest.mark.asyncio
async def test_cb_memory_filter_applies_category(fresh_db):
    fresh_db.add_memory(42, "fact", "fact one")
    fresh_db.add_memory(42, "note", "note one")

    msg = _message_with_edit()
    cb = _callback(data="mem_filter:note", message=msg)

    await cron_module.cb_memory_filter(cb)

    cb.answer.assert_awaited_once()
    text = msg.edit_text.await_args.args[0]
    assert "note one" in text
    assert "fact one" not in text


@pytest.mark.asyncio
async def test_cmd_memory_summary_triggers_service(fresh_db):
    for i in range(5):
        fresh_db.add_memory(42, "fact", f"fact {i + 1}")

    from bot.services import kb as kb_service
    kb_service.db = fresh_db

    async def fake_gen(*args, **kwargs):
        yield (False, type("C", (), {"message": type("M", (), {"content": "Профиль пользователя."})})())

    msg = _message_with_edit()
    state = MagicMock()
    state.clear = AsyncMock()

    with patch("bot.services.kb.generate_chat_completion", side_effect=fake_gen):
        await cron_module.cmd_memory_summary(msg, state)

    text = msg.answer.await_args.args[0]
    assert "Профиль" in text


def test_memory_pagination_keyboard_single_page_none():
    assert memory_pagination_keyboard(0, 1, "all") is None


def test_memory_pagination_keyboard_has_buttons():
    markup = memory_pagination_keyboard(0, 2, "all")
    assert markup is not None
    assert any("Вперёд" in btn.text for row in markup.inline_keyboard for btn in row)


def test_memory_filter_keyboard_marks_active():
    markup = memory_filter_keyboard("fact")
    texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("✅ 📌 Факты" in t for t in texts)
