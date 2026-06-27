from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.db import Database
from bot.services import images as images_module


def _make_jpeg_bytes() -> bytes:
    """Minimal valid JPEG header; vision model is mocked, content doesn't matter."""
    return bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300")


@pytest.fixture(autouse=True)
def reset_images_module():
    images_module.db = None
    images_module._image_message_map.clear()
    yield
    images_module.db = None
    images_module._image_message_map.clear()


@pytest.fixture
def _fake_bot_completion():
    """Avoid importing bot.bot / bot.routers.completion with a real Telegram token."""
    fake_bot = ModuleType("bot.bot")
    fake_bot.Bot = MagicMock()
    fake_completion = ModuleType("bot.routers.completion")
    fake_completion.refresh_system_prompt = MagicMock()
    modules = {
        "bot.bot": fake_bot,
        "bot.routers.completion": fake_completion,
    }
    originals = {name: __import__("sys").modules.get(name) for name in modules}
    __import__("sys").modules.update(modules)
    yield
    for name, original in originals.items():
        if original is None:
            __import__("sys").modules.pop(name, None)
        else:
            __import__("sys").modules[name] = original


@pytest.mark.asyncio
async def test_answer_question_uses_vision_query(tmp_path, _fake_bot_completion):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    source = tmp_path / "photo.jpg"
    source.write_bytes(_make_jpeg_bytes())
    image_id = real_db.add_image(
        user_id=1,
        telegram_file_id="p",
        local_path=str(source),
        caption=None,
        description="A cat on a sofa.",
        ocr_text="Cat Cafe",
    )

    with patch.object(
        images_module,
        "_vision_query",
        new=AsyncMock(return_value="На фото рыжий кот на диване."),
    ) as mock_vision:
        answer = await images_module.answer_question(1, image_id, "Что на фото?")

    assert "рыжий кот" in answer
    mock_vision.assert_awaited_once()
    call_args = mock_vision.await_args
    assert call_args is not None
    assert call_args.args[0] == str(source)
    assert "Что на фото?" in call_args.args[1]
    assert "Описание фото" in call_args.args[1]
    assert "Cat Cafe" in call_args.args[1]


@pytest.mark.asyncio
async def test_answer_question_wrong_user(tmp_path, _fake_bot_completion):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    source = tmp_path / "photo.jpg"
    source.write_bytes(_make_jpeg_bytes())
    image_id = real_db.add_image(
        user_id=1,
        telegram_file_id="p",
        local_path=str(source),
        caption=None,
        description="x",
        ocr_text=None,
    )

    result = await images_module.answer_question(2, image_id, "Вопрос")
    assert "нет доступа" in result


@pytest.mark.asyncio
async def test_answer_question_missing_file(tmp_path, _fake_bot_completion):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    image_id = real_db.add_image(
        user_id=1,
        telegram_file_id="p",
        local_path=str(tmp_path / "missing.jpg"),
        caption=None,
        description="x",
        ocr_text=None,
    )

    result = await images_module.answer_question(1, image_id, "Вопрос")
    assert "Файл фото недоступен" in result


def test_image_message_mapping():
    images_module.map_description_message(12345, 7)
    assert images_module.image_id_for_message(12345) == 7
    assert images_module.image_id_for_message(999) is None
