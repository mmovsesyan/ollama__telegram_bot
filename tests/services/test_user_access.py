"""Tests for user access-control DB layer and security helpers."""

from unittest.mock import MagicMock

import pytest

from bot.db import Database
from bot.security import is_admin, is_allowed


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "users.db"
    db = Database(str(db_path))
    # Make sure security module uses this test DB.
    import bot.security as sec_module
    sec_module.db = db
    yield db
    sec_module.db = None


class TestUserAccessDb:
    def test_ensure_user_creates_pending_record(self, fresh_db):
        row = fresh_db.ensure_user(42, username="alice", full_name="Alice")
        assert row["user_id"] == 42
        assert row["username"] == "alice"
        assert row["full_name"] == "Alice"
        assert row["status"] == "pending"
        assert row["is_admin"] == 0

    def test_ensure_user_updates_existing(self, fresh_db):
        fresh_db.ensure_user(42, username="alice")
        row = fresh_db.ensure_user(42, full_name="Alice Smith", status="approved")
        assert row["full_name"] == "Alice Smith"
        assert row["status"] == "approved"

    def test_is_user_allowed_only_for_approved(self, fresh_db):
        fresh_db.ensure_user(1)
        fresh_db.ensure_user(2)
        fresh_db.set_user_status(2, "approved")
        assert fresh_db.is_user_allowed(1) is False
        assert fresh_db.is_user_allowed(2) is True
        assert fresh_db.is_user_allowed(99) is False

    def test_is_user_admin(self, fresh_db):
        fresh_db.ensure_user(1)
        fresh_db.set_user_admin(1, True)
        assert fresh_db.is_user_admin(1) is True
        assert fresh_db.is_user_admin(2) is False

    def test_set_user_status_invalid_raises(self, fresh_db):
        fresh_db.ensure_user(1)
        with pytest.raises(ValueError):
            fresh_db.set_user_status(1, "bogus")

    def test_delete_user_removes_access(self, fresh_db):
        fresh_db.ensure_user(1, status="approved")
        assert fresh_db.delete_user(1) is True
        assert fresh_db.get_user(1) is None
        assert fresh_db.is_user_allowed(1) is False

    def test_get_users_by_status(self, fresh_db):
        fresh_db.ensure_user(1)
        fresh_db.ensure_user(2, status="approved")
        fresh_db.ensure_user(3, status="rejected")
        assert [u["user_id"] for u in fresh_db.get_users_by_status("pending")] == [1]
        assert [u["user_id"] for u in fresh_db.get_users_by_status("approved")] == [2]
        assert [u["user_id"] for u in fresh_db.get_users_by_status("rejected")] == [3]

    def test_bootstrap_from_allowed_chat_ids(self, tmp_path, monkeypatch):
        # Module-level import is cached; patch the attribute on the imported
        # module object so _read_allowed_chat_ids sees the test value.
        import bot.settings as settings_module
        monkeypatch.setattr(settings_module, "ALLOWED_CHAT_IDS", "111,222")
        db_path = tmp_path / "bootstrap.db"
        db = Database(str(db_path))
        assert db.is_user_admin(111) is True
        assert db.is_user_allowed(111) is True
        assert db.is_user_admin(222) is False
        assert db.is_user_allowed(222) is True


class TestSecurityHelpers:
    def test_is_allowed_uses_db(self, fresh_db):
        fresh_db.ensure_user(1, status="approved")
        fresh_db.ensure_user(2, status="pending")
        assert is_allowed(1) is True
        assert is_allowed(2) is False

    def test_is_admin_uses_db(self, fresh_db):
        fresh_db.ensure_user(1)
        fresh_db.set_user_admin(1, True)
        assert is_admin(1) is True
        assert is_admin(2) is False

    def test_fallback_when_db_missing(self, monkeypatch):
        monkeypatch.setattr("bot.security.db", None)
        monkeypatch.setattr("bot.security.ALLOWED_CHAT_IDS", "42,43")
        assert is_allowed(42) is True
        assert is_allowed(99) is False
        assert is_admin(42) is True  # fallback treats env-list as allowed
        monkeypatch.setattr("bot.security.ALLOWED_CHAT_IDS", "")
        assert is_allowed(99) is True
