import sys
from pathlib import Path
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
    yield
    images_module.db = None


def test_largest_photo_selects_biggest():
    class _Photo:
        def __init__(self, width, height):
            self.width = width
            self.height = height

    photos = [_Photo(100, 100), _Photo(800, 600), _Photo(300, 300)]
    largest = images_module._largest_photo(photos)
    assert largest.width == 800


def test_unique_local_path_avoids_overwrite(tmp_path):
    existing = tmp_path / "img.jpg"
    existing.write_text("x")
    path = images_module._unique_local_path(tmp_path, "img.jpg")
    assert path != existing
    assert path.parent == tmp_path


@pytest.mark.asyncio
async def test_process_image_persists_and_returns_description(tmp_path):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    source = tmp_path / "source.jpg"
    source.write_bytes(_make_jpeg_bytes())

    with patch.object(
        images_module,
        "describe_image",
        new=AsyncMock(return_value="A cat on a sofa."),
    ):
        with patch.object(
            images_module,
            "ocr_image",
            new=AsyncMock(return_value="Cat Cafe"),
        ):
            image = await images_module.process_image(
                user_id=1,
                telegram_file_id="photo_1",
                source_path=str(source),
                caption="My cat",
                filename="cat.jpg",
                base_dir=str(tmp_path / "data"),
            )

    assert image["caption"] == "My cat"
    assert image["description"] == "A cat on a sofa."
    assert image["ocr_text"] == "Cat Cafe"
    assert Path(image["local_path"]).exists()

    images = real_db.get_images(1)
    assert len(images) == 1
    assert images[0]["description"] == "A cat on a sofa."


@pytest.mark.asyncio
async def test_process_image_no_ocr(tmp_path):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    source = tmp_path / "source.jpg"
    source.write_bytes(_make_jpeg_bytes())

    with patch.object(
        images_module,
        "describe_image",
        new=AsyncMock(return_value="A landscape."),
    ):
        with patch.object(
            images_module,
            "ocr_image",
            new=AsyncMock(return_value=""),
        ):
            image = await images_module.process_image(
                user_id=2,
                telegram_file_id="photo_2",
                source_path=str(source),
                caption=None,
                filename="landscape.jpg",
                base_dir=str(tmp_path / "data"),
            )

    assert image["ocr_text"] == ""
    assert real_db.get_images(2)[0]["ocr_text"] is None


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
    originals = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    yield
    for name, original in originals.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


@pytest.mark.asyncio
async def test_save_description_to_memory(tmp_path, _fake_bot_completion):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    source = tmp_path / "source.jpg"
    source.write_bytes(_make_jpeg_bytes())
    image_id = real_db.add_image(
        user_id=1,
        telegram_file_id="p",
        local_path=str(source),
        caption=None,
        description="User likes red cars.",
        ocr_text=None,
    )

    result = await images_module.save_description_to_memory(1, image_id)

    assert "Сохранил" in result
    memories = real_db.get_memories(1)
    assert any("red cars" in m.get("content", "") for m in memories)


@pytest.mark.asyncio
async def test_save_description_to_memory_wrong_user(tmp_path):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    image_id = real_db.add_image(
        user_id=1,
        telegram_file_id="p",
        local_path=str(tmp_path / "x.jpg"),
        caption=None,
        description="x",
        ocr_text=None,
    )
    result = await images_module.save_description_to_memory(2, image_id)
    assert "нет доступа" in result


def test_delete_image_removes_file(tmp_path):
    db_path = tmp_path / "test.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    path = tmp_path / "todelete.jpg"
    path.write_bytes(_make_jpeg_bytes())
    image_id = real_db.add_image(
        user_id=1,
        telegram_file_id="p",
        local_path=str(path),
        caption=None,
        description="x",
        ocr_text=None,
    )
    assert images_module.delete_image(image_id, user_id=1)
    assert not path.exists()


def test_delete_image_unknown_returns_false(tmp_path):
    images_module.db = Database(str(tmp_path / "test.db"))
    assert not images_module.delete_image(999)


def test_delete_image_enforces_ownership(tmp_path):
    db_path = tmp_path / "isolation.db"
    real_db = Database(str(db_path))
    images_module.db = real_db

    path_a = tmp_path / "a.jpg"
    path_a.write_bytes(_make_jpeg_bytes())
    image_id_a = real_db.add_image(
        user_id=1,
        telegram_file_id="p1",
        local_path=str(path_a),
        caption=None,
        description="a",
        ocr_text=None,
    )

    assert images_module.delete_image(image_id_a, user_id=2) is False
    assert path_a.exists()
    assert real_db.get_image(image_id_a) is not None

    assert images_module.delete_image(image_id_a, user_id=1) is True
    assert not path_a.exists()
    assert real_db.get_image(image_id_a) is None
