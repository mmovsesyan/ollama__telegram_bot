import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.db import Database
from bot.services import retention as retention_module


def _utc_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.fixture
def fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    retention_module.db = db
    yield db
    retention_module.db = None


@pytest.fixture(autouse=True)
def reset_state():
    retention_module.db = None
    yield
    retention_module.db = None


def test_cleanup_user_retention_deletes_old_document(fresh_db, tmp_path):
    fresh_db.set_user_prefs(1, retention_days=30)

    old_file = tmp_path / "old.txt"
    old_file.write_text("old content")
    fresh_db.add_document(
        user_id=1,
        telegram_file_id="d1",
        local_path=str(old_file),
        filename="old.txt",
        mime_type="text/plain",
        extracted_text="old",
        summary=None,
    )

    # Simulate old created_at by direct update (the DB default is CURRENT_TIMESTAMP).
    with sqlite3.connect(fresh_db.db_path) as conn:
        conn.execute(
            "UPDATE documents SET created_at = ? WHERE user_id = 1",
            (_utc_days_ago(31),),
        )
        conn.commit()

    docs, images = retention_module.cleanup_user_retention(1)
    assert docs == 1
    assert images == 0
    assert not old_file.exists()
    assert fresh_db.get_documents(1) == []


def test_cleanup_user_retention_keeps_recent_document(fresh_db, tmp_path):
    fresh_db.set_user_prefs(2, retention_days=30)

    recent_file = tmp_path / "recent.txt"
    recent_file.write_text("recent content")
    fresh_db.add_document(
        user_id=2,
        telegram_file_id="d2",
        local_path=str(recent_file),
        filename="recent.txt",
        mime_type="text/plain",
        extracted_text="recent",
        summary=None,
    )

    docs, images = retention_module.cleanup_user_retention(2)
    assert docs == 0
    assert images == 0
    assert recent_file.exists()
    assert len(fresh_db.get_documents(2)) == 1


def test_cleanup_user_retention_respects_keep_forever(fresh_db, tmp_path):
    fresh_db.set_user_prefs(3, retention_days=0)

    old_file = tmp_path / "old_keep.txt"
    old_file.write_text("keep")
    fresh_db.add_document(
        user_id=3,
        telegram_file_id="d3",
        local_path=str(old_file),
        filename="old_keep.txt",
        mime_type="text/plain",
        extracted_text="keep",
        summary=None,
    )
    with sqlite3.connect(fresh_db.db_path) as conn:
        conn.execute(
            "UPDATE documents SET created_at = ? WHERE user_id = 3",
            (_utc_days_ago(365),),
        )
        conn.commit()

    docs, images = retention_module.cleanup_user_retention(3)
    assert docs == 0
    assert images == 0
    assert old_file.exists()



def test_cleanup_user_retention_deletes_old_image(fresh_db, tmp_path):
    fresh_db.set_user_prefs(4, retention_days=30)

    old_image = tmp_path / "old.jpg"
    old_image.write_bytes(b"jpg")
    fresh_db.add_image(
        user_id=4,
        telegram_file_id="i1",
        local_path=str(old_image),
        caption=None,
        description=None,
        ocr_text=None,
    )
    with sqlite3.connect(fresh_db.db_path) as conn:
        conn.execute(
            "UPDATE images SET created_at = ? WHERE user_id = 4",
            (_utc_days_ago(31),),
        )
        conn.commit()

    docs, images = retention_module.cleanup_user_retention(4)
    assert docs == 0
    assert images == 1
    assert not old_image.exists()
    assert fresh_db.get_images(4) == []


def test_cleanup_user_retention_does_not_touch_other_users(fresh_db, tmp_path):
    """Critical: user A's cleanup must not delete user B's documents/images."""
    fresh_db.set_user_prefs(10, retention_days=30)
    fresh_db.set_user_prefs(20, retention_days=30)

    user_a_doc = tmp_path / "a.txt"
    user_a_doc.write_text("a")
    fresh_db.add_document(
        user_id=10,
        telegram_file_id="d10",
        local_path=str(user_a_doc),
        filename="a.txt",
        mime_type="text/plain",
        extracted_text="a",
        summary=None,
    )
    user_b_doc = tmp_path / "b.txt"
    user_b_doc.write_text("b")
    fresh_db.add_document(
        user_id=20,
        telegram_file_id="d20",
        local_path=str(user_b_doc),
        filename="b.txt",
        mime_type="text/plain",
        extracted_text="b",
        summary=None,
    )

    user_a_img = tmp_path / "a.jpg"
    user_a_img.write_bytes(b"a")
    fresh_db.add_image(
        user_id=10,
        telegram_file_id="i10",
        local_path=str(user_a_img),
        caption=None,
        description=None,
        ocr_text=None,
    )
    user_b_img = tmp_path / "b.jpg"
    user_b_img.write_bytes(b"b")
    fresh_db.add_image(
        user_id=20,
        telegram_file_id="i20",
        local_path=str(user_b_img),
        caption=None,
        description=None,
        ocr_text=None,
    )

    with sqlite3.connect(fresh_db.db_path) as conn:
        conn.execute(
            "UPDATE documents SET created_at = ? WHERE user_id = 10",
            (_utc_days_ago(31),),
        )
        conn.execute(
            "UPDATE documents SET created_at = ? WHERE user_id = 20",
            (_utc_days_ago(31),),
        )
        conn.execute(
            "UPDATE images SET created_at = ? WHERE user_id = 10",
            (_utc_days_ago(31),),
        )
        conn.execute(
            "UPDATE images SET created_at = ? WHERE user_id = 20",
            (_utc_days_ago(31),),
        )
        conn.commit()

    docs, images = retention_module.cleanup_user_retention(10)
    assert docs == 1
    assert images == 1
    assert not user_a_doc.exists()
    assert not user_a_img.exists()
    assert user_b_doc.exists()
    assert user_b_img.exists()
    assert len(fresh_db.get_documents(20)) == 1
    assert len(fresh_db.get_images(20)) == 1
