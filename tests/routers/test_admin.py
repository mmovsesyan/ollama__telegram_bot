"""Tests for admin command handlers in bot.routers.cron."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.db import Database
from bot.routers import cron as cron_module
from bot.security import is_admin


def _message(user_id: int = 42, text: str = "", bot=None):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.username = None
    msg.from_user.full_name = f"User {user_id}"
    msg.text = text
    msg.answer = AsyncMock()
    msg.bot = bot or MagicMock()
    msg.bot.send_message = AsyncMock()
    return msg


def _callback(user_id: int = 42, data: str = ""):
    cb = MagicMock()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.answer = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.bot = MagicMock()
    cb.bot.send_message = AsyncMock()
    return cb


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "admin.db"
    db = Database(str(db_path))
    cron_module.db = db
    import bot.security as sec_module

    sec_module.db = db
    yield db
    cron_module.db = None
    sec_module.db = None


@pytest.mark.asyncio
async def test_pending_user_start_sends_request(fresh_db):
    from bot.routers import start as start_module

    start_module.db = fresh_db
    import bot.security as sec_module

    sec_module.db = fresh_db

    try:
        msg = _message(user_id=101, text="/start")
        state = MagicMock()
        state.clear = AsyncMock()
        await start_module.start_command(msg, state)
        text = msg.answer.await_args.args[0]
        assert "одобрения" in text.lower() or "ожидай" in text.lower()
        assert fresh_db.get_user(101)["status"] == "pending"
    finally:
        start_module.db = None


@pytest.mark.asyncio
async def test_admin_requests_only_for_admins(fresh_db):
    fresh_db.ensure_user(1, status="approved")
    fresh_db.set_user_admin(1, True)
    fresh_db.ensure_user(2, status="pending")

    msg = _message(user_id=1, text="/admin_requests")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cmd_admin_requests(msg, state)
    text = msg.answer.await_args.args[0]
    assert "Запросы" in text
    assert "2" in text

    msg2 = _message(user_id=2, text="/admin_requests")
    await cron_module.cmd_admin_requests(msg2, state)
    text2 = msg2.answer.await_args.args[0]
    assert "доступ" in text2.lower()
    assert fresh_db.is_user_allowed(2) is False


@pytest.mark.asyncio
async def test_admin_approve(fresh_db):
    fresh_db.ensure_user(1, status="approved")
    fresh_db.set_user_admin(1, True)
    fresh_db.ensure_user(2, status="pending")

    msg = _message(user_id=1, text="/admin_approve 2")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cmd_admin_approve(msg, state)
    text = msg.answer.await_args.args[0]
    assert "approved" in text.lower() or "одобрен" in text.lower()
    assert "`2`" in text
    assert fresh_db.is_user_allowed(2) is True
    # Target user should be notified.
    msg.bot.send_message.assert_awaited_once()
    call_kwargs = msg.bot.send_message.await_args.kwargs
    target_msg = call_kwargs.get("text", "")
    assert "одобрен" in target_msg.lower() or "approved" in target_msg.lower()


@pytest.mark.asyncio
async def test_non_admin_gets_feedback(fresh_db):
    fresh_db.ensure_user(1, status="approved")
    fresh_db.set_user_admin(1, False)
    fresh_db.ensure_user(2, status="pending")

    msg = _message(user_id=1, text="/admin_approve 2")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cmd_admin_approve(msg, state)
    text = msg.answer.await_args.args[0]
    assert "администратор" in text.lower() or "admin" in text.lower()
    assert fresh_db.is_user_allowed(2) is False


@pytest.mark.asyncio
async def test_unallowed_user_gets_feedback(fresh_db):
    fresh_db.ensure_user(1, status="pending")
    fresh_db.ensure_user(2, status="pending")

    msg = _message(user_id=1, text="/admin_approve 2")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cmd_admin_approve(msg, state)
    text = msg.answer.await_args.args[0]
    assert "доступ" in text.lower()
    assert fresh_db.is_user_allowed(2) is False


@pytest.mark.asyncio
async def test_admin_reject_self_blocked_forbidden(fresh_db):
    fresh_db.ensure_user(1, status="approved")
    fresh_db.set_user_admin(1, True)

    msg = _message(user_id=1, text="/admin_reject 1")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cmd_admin_reject(msg, state)
    text = msg.answer.await_args.args[0]
    assert "себе" in text.lower()
    assert fresh_db.is_user_allowed(1) is True


@pytest.mark.asyncio
async def test_admin_remove_requires_admin(fresh_db):
    fresh_db.ensure_user(1, status="approved")
    fresh_db.set_user_admin(1, True)
    fresh_db.ensure_user(2, status="approved")

    msg = _message(user_id=3, text="/admin_remove 2")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cmd_admin_remove(msg, state)
    text = msg.answer.await_args.args[0]
    assert "доступ" in text.lower() or "admin" in text.lower()
    assert fresh_db.is_user_allowed(2) is True


@pytest.mark.asyncio
async def test_admin_callback_only_for_admins(fresh_db):
    fresh_db.ensure_user(1, status="approved")
    fresh_db.set_user_admin(1, True)
    fresh_db.ensure_user(2, status="pending")

    cb = _callback(user_id=1, data="admin:approve:2")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cb_admin_action(cb, state)
    assert fresh_db.is_user_allowed(2) is True

    fresh_db.ensure_user(3, status="pending")
    cb2 = _callback(user_id=2, data="admin:approve:3")
    await cron_module.cb_admin_action(cb2, state)
    assert fresh_db.is_user_allowed(3) is False


@pytest.mark.asyncio
async def test_non_admin_cannot_promote(fresh_db):
    fresh_db.ensure_user(1, status="approved")
    fresh_db.ensure_user(2, status="approved")

    msg = _message(user_id=2, text="/admin_promote 2")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cmd_admin_promote(msg, state)
    text = msg.answer.await_args.args[0]
    assert "администратор" in text.lower() or "admin" in text.lower()
    assert is_admin(2) is False


@pytest.mark.asyncio
async def test_admin_remove_cascade_deletes_user_data_and_files(fresh_db, tmp_path):
    fresh_db.ensure_user(1, status="approved")
    fresh_db.set_user_admin(1, True)
    fresh_db.ensure_user(2, status="approved")

    doc_file = tmp_path / "target_doc.txt"
    doc_file.write_text("target content", encoding="utf-8")
    fresh_db.add_document(
        2, "f2", str(doc_file), "target_doc.txt", "text/plain", "target content", None
    )

    img_file = tmp_path / "target_img.jpg"
    img_file.write_bytes(b"targetjpg")
    fresh_db.add_image(2, "p2", str(img_file), None, None, None)

    msg = _message(user_id=1, text="/admin_remove 2")
    state = MagicMock()
    state.clear = AsyncMock()
    await cron_module.cmd_admin_remove(msg, state)

    assert fresh_db.get_user(2) is None
    assert not doc_file.exists()
    assert not img_file.exists()
    assert msg.answer.await_args is not None
    answer_text = msg.answer.await_args.args[0]
    assert "2" in answer_text
    assert "удален" in answer_text.lower()
