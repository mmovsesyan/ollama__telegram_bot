import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if "bot.bot" not in sys.modules:
    _fake_bot_module = ModuleType("bot.bot")
    _fake_bot_module.bot = MagicMock()
    sys.modules["bot.bot"] = _fake_bot_module

from bot.db import Database
from bot.routers import completion as completion_module
from bot.services import images as images_module


def _message(user_id: int = 42, caption: str | None = None):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.caption = caption
    msg.answer = AsyncMock()
    return msg


def _photo(width: int, height: int, file_id: str = "photo_42"):
    photo = MagicMock()
    photo.width = width
    photo.height = height
    photo.file_id = file_id
    return photo


def _callback(user_id: int = 42, data: str = "img_close", message=None):
    cb = MagicMock()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.data = data
    cb.message = message
    cb.answer = AsyncMock()
    return cb


@pytest.fixture(autouse=True)
def reset_state():
    completion_module.db = None
    images_module.db = None
    yield
    completion_module.db = None
    images_module.db = None


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    completion_module.db = db
    images_module.db = db
    yield db
    completion_module.db = None
    images_module.db = None


@pytest.mark.asyncio
async def test_handle_photo_processes_and_replies(fresh_db):
    photos = [_photo(100, 100, "small"), _photo(800, 600, "big")]
    msg = _message(caption="Test caption")
    msg.photo = photos
    state = MagicMock()
    state.clear = AsyncMock()

    fake_file = MagicMock()
    fake_file.file_path = "photos/big.jpg"

    with patch.object(
        completion_module.aiogram_bot, "get_file", new=AsyncMock(return_value=fake_file)
    ):
        with patch.object(
            completion_module.aiogram_bot, "download_file", new=AsyncMock()
        ) as download_mock:
            download_mock.side_effect = lambda _, dest: Path(dest).write_bytes(
                _make_jpeg_bytes()
            )
            with patch.object(
                images_module,
                "describe_image",
                new=AsyncMock(return_value="A sunset over the sea."),
            ):
                with patch.object(
                    images_module,
                    "ocr_image",
                    new=AsyncMock(return_value="Sample text"),
                ):
                    await completion_module.handle_photo(msg, state)

    msg.answer.assert_awaited()
    assert msg.answer.await_count == 2
    final_text = msg.answer.await_args.args[0]
    assert "A sunset over the sea." in final_text
    assert "Sample text" in final_text

    images = fresh_db.get_images(42)
    assert len(images) == 1
    assert images[0]["caption"] == "Test caption"


@pytest.mark.asyncio
async def test_handle_photo_no_photos_ignores():
    msg = _message()
    msg.photo = []
    state = MagicMock()
    await completion_module.handle_photo(msg, state)
    msg.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_cb_save_image_to_memory(fresh_db, tmp_path):
    path = tmp_path / "mem_test.jpg"
    path.write_bytes(_make_jpeg_bytes())
    image_id = fresh_db.add_image(
        user_id=42,
        telegram_file_id="p",
        local_path=str(path),
        caption=None,
        description="User has a red bicycle.",
        ocr_text=None,
    )

    fake_completion = ModuleType("bot.routers.completion")
    fake_completion.refresh_system_prompt = MagicMock()
    original = sys.modules.get("bot.routers.completion")
    sys.modules["bot.routers.completion"] = fake_completion

    try:
        msg = MagicMock()
        msg.edit_text = AsyncMock()
        cb = _callback(user_id=42, data=f"img_save:{image_id}", message=msg)
        state = MagicMock()
        state.clear = AsyncMock()

        await completion_module.cb_save_image_to_memory(cb, state)

        cb.answer.assert_awaited_once()
        msg.edit_text.assert_awaited_once()
        assert "Сохранил" in msg.edit_text.await_args.args[0]
        assert any(
            "red bicycle" in m.get("content", "") for m in fresh_db.get_memories(42)
        )
    finally:
        if original is None:
            sys.modules.pop("bot.routers.completion", None)
        else:
            sys.modules["bot.routers.completion"] = original


@pytest.mark.asyncio
async def test_cb_image_close_removes_keyboard():
    msg = MagicMock()
    msg.edit_reply_markup = AsyncMock()
    cb = _callback(message=msg)
    state = MagicMock()
    state.clear = AsyncMock()

    await completion_module.cb_image_close(cb, state)

    cb.answer.assert_awaited_once()
    msg.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


def _make_jpeg_bytes() -> bytes:
    return bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300")
