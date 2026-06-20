"""Tests for user access-control DB layer and security helpers."""

import sqlite3

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


class TestCascadeDeletion:
    def test_delete_user_cascade_removes_all_data_and_files(self, fresh_db, tmp_path):
        target = 11
        other = 22

        fresh_db.ensure_user(target, status="approved")
        fresh_db.ensure_user(other, status="approved")

        # Preferences
        fresh_db.set_user_prefs(target, language="ru")
        fresh_db.set_user_prefs(other, language="en")

        # Session + messages + summary
        target_session = fresh_db.get_or_create_active_session(target, "model-x")
        fresh_db.save_message(target, target_session, "user", "hello target")
        fresh_db.add_summary(target_session, 1, "target summary")

        other_session = fresh_db.get_or_create_active_session(other, "model-y")
        fresh_db.save_message(other, other_session, "user", "hello other")
        fresh_db.add_summary(other_session, 1, "other summary")

        # Reminders, monitors, memories, shown news
        fresh_db.add_reminder(target, "target reminder")
        fresh_db.add_monitor(target, "target site", "http://target.example")
        fresh_db.add_memory(target, "fact", "target likes tea")
        fresh_db.mark_news_shown(target, "http://news/target", "target news")

        fresh_db.add_reminder(other, "other reminder")
        fresh_db.add_monitor(other, "other site", "http://other.example")
        fresh_db.add_memory(other, "fact", "other likes coffee")
        fresh_db.mark_news_shown(other, "http://news/other", "other news")

        # Documents + images with real temp files
        target_doc = tmp_path / "target.txt"
        target_doc.write_text("target doc", encoding="utf-8")
        target_img = tmp_path / "target.jpg"
        target_img.write_bytes(b"targetjpg")
        other_doc = tmp_path / "other.txt"
        other_doc.write_text("other doc", encoding="utf-8")
        other_img = tmp_path / "other.jpg"
        other_img.write_bytes(b"otherjpg")

        target_doc_id = fresh_db.add_document(
            target,
            "f_target",
            str(target_doc),
            "target.txt",
            "text/plain",
            "target doc",
            None,
        )
        fresh_db.add_document_chunks(target_doc_id, target, ["target chunk"])
        fresh_db.add_image(target, "p_target", str(target_img), None, None, None)

        other_doc_id = fresh_db.add_document(
            other,
            "f_other",
            str(other_doc),
            "other.txt",
            "text/plain",
            "other doc",
            None,
        )
        fresh_db.add_document_chunks(other_doc_id, other, ["other chunk"])
        fresh_db.add_image(other, "p_other", str(other_img), None, None, None)

        assert fresh_db.delete_user(target) is True

        # Target must be gone from users table
        assert fresh_db.get_user(target) is None

        # Target data must be gone from every user-scoped table
        user_tables = [
            "messages",
            "sessions",
            "user_prefs",
            "reminders",
            "monitors",
            "memories",
            "shown_news",
            "documents",
            "images",
        ]
        with sqlite3.connect(fresh_db.db_path) as conn:
            for table in user_tables:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?",  # Test-only introspection of known table names.  # nosec B608
                    (target,),
                ).fetchone()[0]
                assert count == 0, f"{table} still has rows for target user"

            # Summaries tied to target sessions must be gone
            target_summary_count = conn.execute(
                "SELECT COUNT(*) FROM summaries WHERE session_id = ?", (target_session,)
            ).fetchone()[0]
            assert (
                target_summary_count == 0
            ), "summaries still has rows for target session"

            # Other user's data must remain
            for table in user_tables:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?",  # Test-only introspection of known table names.  # nosec B608
                    (other,),
                ).fetchone()[0]
                assert count > 0, f"{table} lost rows for other user"

            # Other summary and chunks must remain
            other_summary_count = conn.execute(
                "SELECT COUNT(*) FROM summaries WHERE session_id = ?", (other_session,)
            ).fetchone()[0]
            assert other_summary_count == 1, "other summary was removed"

            other_chunk_count = conn.execute(
                "SELECT COUNT(*) FROM document_chunks_fts WHERE document_id = ?",
                (other_doc_id,),
            ).fetchone()[0]
            assert other_chunk_count == 1, "other document chunks were removed"

        # Files
        assert not target_doc.exists()
        assert not target_img.exists()
        assert other_doc.exists()
        assert other_img.exists()

    def test_delete_user_isolation_does_not_affect_other_users(
        self, fresh_db, tmp_path
    ):
        """Even if two users share a filename/path pattern, only target is hit."""
        target = 31
        other = 32
        fresh_db.ensure_user(target, status="approved")
        fresh_db.ensure_user(other, status="approved")

        target_file = tmp_path / "shared_name.txt"
        target_file.write_text("target", encoding="utf-8")
        other_file = tmp_path / "shared_name_other.txt"
        other_file.write_text("other", encoding="utf-8")

        fresh_db.add_document(
            target,
            "f1",
            str(target_file),
            "shared_name.txt",
            "text/plain",
            "target",
            None,
        )
        fresh_db.add_document(
            other, "f2", str(other_file), "shared_name.txt", "text/plain", "other", None
        )

        assert fresh_db.delete_user(target) is True
        assert not target_file.exists()
        assert other_file.exists()
        assert len(fresh_db.get_documents(other)) == 1

    def test_delete_user_returns_false_when_user_missing(self, fresh_db):
        assert fresh_db.delete_user(9999) is False

    def test_delete_user_ignores_path_traversal_local_path(self, tmp_path, monkeypatch):
        """A malicious local_path outside data/<user_id> must not be deleted.

        We create a fresh Database whose data directory already contains the
        user's docs tree, so the guard sees the expected path exists and rejects
        the traversal path.
        """

        target = 41

        # Prepare user data dir *before* the Database object is created.
        user_dir = tmp_path / "data" / str(target) / "docs"
        user_dir.mkdir(parents=True, exist_ok=True)
        legit = user_dir / "legit.txt"
        legit.write_text("delete me", encoding="utf-8")

        # File the attacker wants to delete (outside their data dir).
        victim = tmp_path / "victim.txt"
        victim.write_text("keep me", encoding="utf-8")

        db_path = tmp_path / "data" / "users.db"
        fresh_db = Database(str(db_path))
        fresh_db.ensure_user(target, status="approved")

        fresh_db.add_document(
            target,
            "f1",
            str(victim),
            "../victim.txt",
            "text/plain",
            "bad",
            None,
        )
        fresh_db.add_document(
            target,
            "f2",
            str(legit),
            "legit.txt",
            "text/plain",
            "good",
            None,
        )

        assert fresh_db.delete_user(target) is True
        assert victim.exists(), "path outside user dir was incorrectly deleted"
        assert not legit.exists(), "legit file inside user dir was not deleted"
