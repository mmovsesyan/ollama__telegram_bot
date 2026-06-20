import sqlite3
from pathlib import Path
from typing import Any, Optional

from bot.settings import ALLOWED_CHAT_IDS as _ALLOWED_CHAT_IDS

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        # If migrating from a pre-FTS DB, populate the index from existing rows.
        # No-op when the index is already in sync.
        try:
            self.backfill_memories_fts()
        except Exception:
            pass

    def _read_allowed_chat_ids(self) -> str:
        """Read env allow-list fresh via module attribute, not a local binding."""
        import bot.settings as settings_module
        return getattr(settings_module, "ALLOWED_CHAT_IDS", "") or ""

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Migrate reminders table: add action column if missing
            try:
                conn.execute("ALTER TABLE reminders ADD COLUMN action TEXT DEFAULT 'notify'")
            except sqlite3.OperationalError:
                pass
            # Migrate monitors table: persist alert state across restarts
            try:
                conn.execute("ALTER TABLE monitors ADD COLUMN alerted INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            # Migrate user_prefs: add display name and timezone for localization
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN name TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN timezone TEXT DEFAULT 'UTC'")
            except sqlite3.OperationalError:
                pass
            # Migrate memories: optional LLM-compressed summary for long entries.
            # FTS5 indexes both content and summary so search hits either.
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN summary TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'manual'")
            except sqlite3.OperationalError:
                pass
            # Migrate user_prefs: proactive/morning-briefing settings.
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN briefing_enabled INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN briefing_time TEXT DEFAULT '08:00'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN proactive_enabled INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN news_categories TEXT DEFAULT 'tech,markets,ai'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN voice_output_enabled INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN briefing_city TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN last_briefing_date TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN smart_reminders_enabled INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN digest_enabled INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN digest_time TEXT DEFAULT '20:00'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN last_digest_date TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE user_prefs ADD COLUMN retention_days INTEGER DEFAULT 90")
            except sqlite3.OperationalError:
                pass
            # New users/access-control table.
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','blocked')),
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_by INTEGER,
                    is_admin INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
                CREATE INDEX IF NOT EXISTS idx_users_admin ON users(is_admin);
            """)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    session_id INTEGER,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    model TEXT,
                    summary TEXT,
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_prefs (
                    user_id INTEGER PRIMARY KEY,
                    default_model TEXT,
                    language TEXT DEFAULT 'ru',
                    style TEXT DEFAULT 'concise',
                    notes TEXT,
                    name TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    briefing_enabled INTEGER DEFAULT 1,
                    briefing_time TEXT DEFAULT '08:00',
                    proactive_enabled INTEGER DEFAULT 1,
                    news_categories TEXT DEFAULT 'tech,markets,ai',
                    voice_output_enabled INTEGER DEFAULT 0,
                    briefing_city TEXT,
                    last_briefing_date TEXT,
                    smart_reminders_enabled INTEGER DEFAULT 1,
                    digest_enabled INTEGER DEFAULT 0,
                    digest_time TEXT DEFAULT '20:00',
                    last_digest_date TEXT,
                    retention_days INTEGER DEFAULT 90,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    trigger_at TIMESTAMP,
                    recurring TEXT,
                    enabled INTEGER DEFAULT 1,
                    action TEXT DEFAULT 'notify',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS monitors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    method TEXT DEFAULT 'GET',
                    expected_status INTEGER DEFAULT 200,
                    check_interval INTEGER DEFAULT 300,
                    last_check TIMESTAMP,
                    last_status INTEGER,
                    enabled INTEGER DEFAULT 1,
                    alerted INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    message_count INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    category TEXT DEFAULT 'fact',
                    content TEXT NOT NULL,
                    summary TEXT,
                    source TEXT DEFAULT 'manual',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Full-text search over memories. Sync via triggers below.
                -- Indexes both raw content and the optional LLM summary so a
                -- query hits whichever form is more discoverable.
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content,
                    summary,
                    user_id UNINDEXED,
                    category UNINDEXED,
                    content='memories',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );

                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content, summary, user_id, category)
                    VALUES (new.id, new.content, COALESCE(new.summary, ''), new.user_id, new.category);
                END;

                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, summary, user_id, category)
                    VALUES ('delete', old.id, old.content, COALESCE(old.summary, ''), old.user_id, old.category);
                END;

                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, summary, user_id, category)
                    VALUES ('delete', old.id, old.content, COALESCE(old.summary, ''), old.user_id, old.category);
                    INSERT INTO memories_fts(rowid, content, summary, user_id, category)
                    VALUES (new.id, new.content, COALESCE(new.summary, ''), new.user_id, new.category);
                END;

                CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id);
                CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
                CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(enabled, trigger_at);
                CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id, enabled);

                CREATE TABLE IF NOT EXISTS shown_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    shown_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, url)
                );
                CREATE INDEX IF NOT EXISTS idx_shown_news_user ON shown_news(user_id, shown_at);

                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    telegram_file_id TEXT,
                    local_path TEXT,
                    filename TEXT,
                    mime_type TEXT,
                    extracted_text TEXT,
                    summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id, created_at);

                CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
                    chunk,
                    document_id UNINDEXED,
                    user_id UNINDEXED
                );

                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    telegram_file_id TEXT,
                    local_path TEXT,
                    caption TEXT,
                    description TEXT,
                    ocr_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_images_user ON images(user_id, created_at);
            """)
            self._bootstrap_users_from_env(conn)

    def _bootstrap_users_from_env(self, conn: sqlite3.Connection) -> None:
        """If ALLOWED_CHAT_IDS is set, seed the users table with approved users
        and make the first listed ID an admin. Does nothing if users already exist.
        """
        raw = self._read_allowed_chat_ids()
        if not raw:
            return
        cursor = conn.execute("SELECT 1 FROM users LIMIT 1")
        if cursor.fetchone():
            return
        ids = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
        if not ids:
            return
        for i, uid in enumerate(ids):
            is_admin = 1 if i == 0 else 0
            conn.execute(
                "INSERT INTO users (user_id, status, is_admin, approved_by) VALUES (?, 'approved', ?, ?)",
                (uid, is_admin, uid if is_admin else None),
            )
        conn.commit()

    def get_or_create_active_session(self, user_id: int, model: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM sessions WHERE user_id = ? AND active = 1 ORDER BY updated_at DESC LIMIT 1",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                session_id = row[0]
                conn.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
                conn.commit()
                return session_id

            cursor = conn.execute(
                "INSERT INTO sessions (user_id, model) VALUES (?, ?)",
                (user_id, model)
            )
            conn.commit()
            return cursor.lastrowid

    def close_session(self, session_id: int, summary: Optional[str] = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET active = 0, summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (summary, session_id)
            )
            conn.commit()

    def get_session_messages(self, user_id: int, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT id FROM sessions WHERE user_id = ? AND active = 1 ORDER BY updated_at DESC LIMIT 1",
                (user_id,)
            )
            row = cursor.fetchone()
            if not row:
                return []
            session_id = row[0]
            cursor = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit)
            )
            rows = cursor.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def save_message(self, user_id: int, session_id: int, role: str, content: str, model: Optional[str] = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (user_id, session_id, role, content, model) VALUES (?, ?, ?, ?, ?)",
                (user_id, session_id, role, content, model)
            )
            conn.commit()

    def get_user_prefs(self, user_id: int) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM user_prefs WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def set_user_prefs(self, user_id: int, **kwargs):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM user_prefs WHERE user_id = ?", (user_id,))
            if cursor.fetchone():
                fields = []
                values = []
                for k, v in kwargs.items():
                    fields.append(f"{k} = ?")
                    values.append(v)
                values.append(user_id)
                conn.execute(
                    f"UPDATE user_prefs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                    values
                )
            else:
                fields = list(kwargs.keys())
                placeholders = ', '.join(['?' for _ in fields])
                conn.execute(
                    f"INSERT INTO user_prefs (user_id, {', '.join(fields)}) VALUES (?, {placeholders})",
                    [user_id] + list(kwargs.values())
                )
            conn.commit()

    def add_note(self, user_id: int, note: str):
        prefs = self.get_user_prefs(user_id) or {}
        notes = prefs.get('notes', '') or ''
        notes = notes + f"\n- {note}" if notes else f"- {note}"
        self.set_user_prefs(user_id, notes=notes)

    def get_notes(self, user_id: int) -> str:
        prefs = self.get_user_prefs(user_id)
        if prefs and prefs.get('notes'):
            return prefs['notes']
        return ""

    def add_reminder(self, user_id: int, content: str, trigger_at: Optional[str] = None, recurring: Optional[str] = None, action: Optional[str] = None) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO reminders (user_id, content, trigger_at, recurring, action) VALUES (?, ?, ?, ?, ?)",
                (user_id, content, trigger_at, recurring, action)
            )
            conn.commit()
            return cursor.lastrowid

    def get_pending_reminders(self, before: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM reminders WHERE enabled = 1 AND trigger_at IS NOT NULL AND trigger_at <= ? ORDER BY trigger_at",
                (before,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_user_reminders(self, user_id: int) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM reminders WHERE user_id = ? AND enabled = 1 ORDER BY trigger_at",
                (user_id,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def reschedule_reminder(self, reminder_id: int, new_trigger_at: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE reminders SET trigger_at = ? WHERE id = ?",
                (new_trigger_at, reminder_id)
            )
            conn.commit()

    def update_reminder_content(self, reminder_id: int, new_content: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE reminders SET content = ? WHERE id = ?",
                (new_content, reminder_id),
            )
            conn.commit()

    def update_reminder_schedule(self, reminder_id: int, trigger_at: str, recurring: str | None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE reminders SET trigger_at = ?, recurring = ? WHERE id = ?",
                (trigger_at, recurring, reminder_id),
            )
            conn.commit()

    def get_reminder(self, reminder_id: int) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def disable_reminder(self, reminder_id: int):
        """Hard-delete the reminder. Kept the name `disable_reminder` for
        backward compat with callers; behavior is now permanent removal so
        DB-side ids don't accumulate after the user clears their list."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            conn.commit()

    def delete_reminder(self, reminder_id: int):
        """Alias for disable_reminder; new callers should prefer this name."""
        self.disable_reminder(reminder_id)

    def add_monitor(self, user_id: int, name: str, url: str, method: str = 'GET', expected_status: int = 200, interval: int = 300) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO monitors (user_id, name, url, method, expected_status, check_interval) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, name, url, method, expected_status, interval)
            )
            conn.commit()
            return cursor.lastrowid

    def get_monitors(self, user_id: int) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM monitors WHERE user_id = ? AND enabled = 1", (user_id,))
            return [dict(r) for r in cursor.fetchall()]

    def get_all_active_monitors(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM monitors WHERE enabled = 1")
            return [dict(r) for r in cursor.fetchall()]

    def update_monitor_status(self, monitor_id: int, last_status: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitors SET last_check = CURRENT_TIMESTAMP, last_status = ? WHERE id = ?",
                (last_status, monitor_id)
            )
            conn.commit()

    def set_monitor_alerted(self, monitor_id: int, alerted: bool):
        """Persist whether the monitor is currently in 'alert' state.

        Survives restart so users don't get duplicate ALERTs and recovery
        messages still fire after downtime."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitors SET alerted = ? WHERE id = ?",
                (1 if alerted else 0, monitor_id),
            )
            conn.commit()

    def is_monitor_alerted(self, monitor_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT alerted FROM monitors WHERE id = ?", (monitor_id,))
            row = cursor.fetchone()
            return bool(row[0]) if row and row[0] is not None else False

    def remove_monitor(self, monitor_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
            conn.commit()

    def add_summary(self, session_id: int, message_count: int, summary: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO summaries (session_id, message_count, summary) VALUES (?, ?, ?)",
                (session_id, message_count, summary)
            )
            conn.commit()
            return cursor.lastrowid

    def get_latest_summary(self, session_id: int) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM summaries WHERE session_id = ? ORDER BY message_count DESC LIMIT 1",
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_all_summaries(self, session_id: int) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM summaries WHERE session_id = ? ORDER BY message_count ASC",
                (session_id,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def add_memory(
        self,
        user_id: int,
        category: str,
        content: str,
        summary: str | None = None,
        source: str = "manual",
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO memories (user_id, category, content, summary, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, category, content, summary, source),
            )
            conn.commit()
            return cursor.lastrowid

    def update_memory_summary(self, memory_id: int, summary: str):
        """Attach an LLM-generated summary to an existing memory. Triggers
        keep the FTS index in sync automatically."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE memories SET summary = ? WHERE id = ?",
                (summary, memory_id),
            )
            conn.commit()

    def search_memories(
        self,
        user_id: int,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """Full-text search over the user's memories. Returns rows ordered
        by FTS5 BM25 relevance.

        Each query token gets a prefix wildcard (foo*) so Russian word
        endings ("яблоки" matches "яблок"). Tokens are ORed by default
        so partial matches still surface; FTS5 ranks the full-match hits
        highest. Returns empty list if FTS is missing (pre-migration)."""
        if not query or not query.strip():
            return []
        # Strip punctuation that breaks FTS5 query syntax.
        cleaned = query.replace('"', " ").replace("'", " ").replace("(", " ").replace(")", " ")
        tokens = [tok.strip() for tok in cleaned.split() if tok.strip()]
        if not tokens:
            return []
        # Prefix wildcard catches inflected forms; OR keeps recall high.
        # FTS5 sorts by BM25 anyway so the most-matching row wins.
        fts_q = " OR ".join(f"{tok}*" for tok in tokens)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    "SELECT m.id, m.user_id, m.category, m.content, m.summary, "
                    "m.source, m.created_at, "
                    "bm25(memories_fts) AS rank "
                    "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
                    "WHERE memories_fts MATCH ? AND m.user_id = ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_q, user_id, limit),
                )
                return [dict(r) for r in cursor.fetchall()]
            except sqlite3.OperationalError:
                return []

    def backfill_memories_fts(self) -> int:
        """One-time helper: populate FTS index from existing memories rows
        when the index is empty (e.g. after migrating an old database).
        Returns the number of rows backfilled."""
        with sqlite3.connect(self.db_path) as conn:
            try:
                fts_count = conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
                mem_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                if fts_count >= mem_count:
                    return 0
                conn.execute(
                    "INSERT INTO memories_fts(rowid, content, summary, user_id, category) "
                    "SELECT id, content, COALESCE(summary, ''), user_id, category FROM memories"
                )
                conn.commit()
                return mem_count - fts_count
            except sqlite3.OperationalError:
                return 0

    def get_memories(self, user_id: int, category: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if category:
                cursor = conn.execute(
                    "SELECT * FROM memories WHERE user_id = ? AND category = ? ORDER BY created_at DESC",
                    (user_id, category)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM memories WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,)
                )
            return [dict(r) for r in cursor.fetchall()]

    def remove_memory(self, memory_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()

    def is_news_shown(self, user_id: int, url: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM shown_news WHERE user_id = ? AND url = ? LIMIT 1",
                (user_id, url)
            )
            return cursor.fetchone() is not None

    def mark_news_shown(self, user_id: int, url: str, title: str | None = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO shown_news (user_id, url, title) VALUES (?, ?, ?)",
                (user_id, url, title)
            )
            conn.commit()

    def cleanup_old_shown_news(self, days: int = 30) -> int:
        """Prune shown-news history older than `days` to keep the table small."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM shown_news WHERE shown_at < datetime('now', ?)",
                (f"-{days} days",)
            )
            conn.commit()
            return cursor.rowcount

    def get_briefing_enabled_users(self) -> list[dict]:
        """Return users who have morning briefing enabled."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT user_id, timezone, briefing_enabled, briefing_time, "
                "proactive_enabled, news_categories, briefing_city, last_briefing_date "
                "FROM user_prefs WHERE briefing_enabled = 1 AND proactive_enabled = 1"
            )
            return [dict(r) for r in cursor.fetchall()]

    def update_briefing_sent(self, user_id: int, date_str: str):
        """Record the last date a morning briefing was sent so we don't
        spam the user if the scheduler ticks multiple times in the same minute."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE user_prefs SET last_briefing_date = ? WHERE user_id = ?",
                (date_str, user_id)
            )
            conn.commit()

    def get_digest_enabled_users(self) -> list[dict]:
        """Return users who have evening digest enabled."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT user_id, timezone, digest_enabled, digest_time, "
                "proactive_enabled, news_categories, briefing_city, last_digest_date "
                "FROM user_prefs WHERE digest_enabled = 1 AND proactive_enabled = 1"
            )
            return [dict(r) for r in cursor.fetchall()]

    def update_digest_sent(self, user_id: int, date_str: str):
        """Record the last date an evening digest was sent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE user_prefs SET last_digest_date = ? WHERE user_id = ?",
                (date_str, user_id)
            )
            conn.commit()

    def get_memories_for_date(
        self,
        user_id: int,
        start_utc_iso: str,
        end_utc_iso: str,
    ) -> list[dict]:
        """Return memories created in a UTC date range."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM memories WHERE user_id = ? AND created_at >= ? AND created_at < ? "
                "ORDER BY created_at DESC",
                (user_id, start_utc_iso, end_utc_iso),
            )
            return [dict(r) for r in cursor.fetchall()]

    def add_document(
        self,
        user_id: int,
        telegram_file_id: str | None,
        local_path: str,
        filename: str,
        mime_type: str | None,
        extracted_text: str,
        summary: str | None,
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO documents
                (user_id, telegram_file_id, local_path, filename, mime_type, extracted_text, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, telegram_file_id, local_path, filename, mime_type, extracted_text, summary),
            )
            conn.commit()
            return cursor.lastrowid

    def get_documents(self, user_id: int) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM documents WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_document(self, doc_id: int, user_id: int | None = None) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if user_id is not None:
                cursor = conn.execute(
                    "SELECT * FROM documents WHERE id = ? AND user_id = ?",
                    (doc_id, user_id),
                )
            else:
                cursor = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_document(self, doc_id: int, user_id: int | None = None) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            if user_id is not None:
                cursor = conn.execute(
                    "DELETE FROM documents WHERE id = ? AND user_id = ?",
                    (doc_id, user_id),
                )
            else:
                cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.execute("DELETE FROM document_chunks_fts WHERE document_id = ?", (doc_id,))
            conn.commit()
            return cursor.rowcount > 0

    def add_document_chunks(self, doc_id: int, user_id: int, chunks: list[str]):
        with sqlite3.connect(self.db_path) as conn:
            for chunk in chunks:
                conn.execute(
                    "INSERT INTO document_chunks_fts (chunk, document_id, user_id) VALUES (?, ?, ?)",
                    (chunk, doc_id, user_id),
                )
            conn.commit()

    def search_document_chunks(self, user_id: int, query: str, limit: int = 5) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT document_id, chunk, rank
                FROM document_chunks_fts
                WHERE document_chunks_fts MATCH ? AND user_id = ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, user_id, limit),
            )
            return [dict(r) for r in cursor.fetchall()]

    def add_image(
        self,
        user_id: int,
        telegram_file_id: str | None,
        local_path: str,
        caption: str | None,
        description: str | None,
        ocr_text: str | None,
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO images
                (user_id, telegram_file_id, local_path, caption, description, ocr_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, telegram_file_id, local_path, caption, description, ocr_text),
            )
            conn.commit()
            return cursor.lastrowid

    def get_images(self, user_id: int) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM images WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_image(self, image_id: int, user_id: int | None = None) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if user_id is not None:
                cursor = conn.execute(
                    "SELECT * FROM images WHERE id = ? AND user_id = ?",
                    (image_id, user_id),
                )
            else:
                cursor = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_image(self, image_id: int, user_id: int | None = None) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            if user_id is not None:
                cursor = conn.execute(
                    "DELETE FROM images WHERE id = ? AND user_id = ?",
                    (image_id, user_id),
                )
            else:
                cursor = conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_old_documents(self, user_id: int, before_utc_iso: str) -> list[dict]:
        """Return a user's documents with created_at older than the cutoff."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM documents WHERE user_id = ? AND created_at < ?",
                (user_id, before_utc_iso),
            )
            return [dict(r) for r in cursor.fetchall()]

    def cleanup_old_documents(self, user_id: int, before_utc_iso: str) -> int:
        """Delete a user's documents older than cutoff and their FTS chunks.

        Returns the number of rows removed. Files are removed by the caller
        so path logging survives the DB transaction."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE user_id = ? AND created_at < ?",
                (user_id, before_utc_iso),
            )
            conn.execute(
                "DELETE FROM document_chunks_fts WHERE document_id NOT IN (SELECT id FROM documents)",
            )
            conn.commit()
            return cursor.rowcount

    def get_old_images(self, user_id: int, before_utc_iso: str) -> list[dict]:
        """Return a user's images with created_at older than the cutoff."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM images WHERE user_id = ? AND created_at < ?",
                (user_id, before_utc_iso),
            )
            return [dict(r) for r in cursor.fetchall()]

    def cleanup_old_images(self, user_id: int, before_utc_iso: str) -> int:
        """Delete a user's images older than cutoff. Returns row count."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM images WHERE user_id = ? AND created_at < ?",
                (user_id, before_utc_iso),
            )
            conn.commit()
            return cursor.rowcount

    def get_all_user_ids(self) -> list[int]:
        """Return every user_id that appears in user_prefs."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT user_id FROM user_prefs")
            return [row[0] for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # User access control
    # ------------------------------------------------------------------

    def ensure_user(
        self,
        user_id: int,
        username: str | None = None,
        full_name: str | None = None,
        status: str | None = None,
    ) -> dict:
        """Insert or update a users row and return the current record."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                record = dict(row)
                fields: list[str] = []
                values: list[Any] = []
                if username is not None:
                    fields.append("username = ?")
                    values.append(username)
                if full_name is not None:
                    fields.append("full_name = ?")
                    values.append(full_name)
                if status is not None and record["status"] != status:
                    fields.append("status = ?")
                    values.append(status)
                if fields:
                    values.append(user_id)
                    conn.execute(
                        f"UPDATE users SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                        values,
                    )
                    conn.commit()
                    cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                    record = dict(cursor.fetchone())
                return record

            # Fresh record: status defaults to pending if not provided.
            insert_status = status or "pending"
            conn.execute(
                """
                INSERT INTO users (user_id, username, full_name, status, requested_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (user_id, username, full_name, insert_status),
            )
            conn.commit()
            cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return dict(cursor.fetchone())

    def get_user(self, user_id: int) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def is_user_allowed(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        return bool(user and user.get("status") == "approved")

    def is_user_admin(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        return bool(user and user.get("is_admin"))

    def set_user_status(
        self,
        user_id: int,
        status: str,
        approved_by: int | None = None,
    ) -> bool:
        if status not in ("pending", "approved", "rejected", "blocked"):
            raise ValueError(f"Invalid user status: {status}")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET status = ?, approved_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (status, approved_by, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_user_admin(self, user_id: int, is_admin: bool) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE users SET is_admin = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (1 if is_admin else 0, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        """Remove the access-control record. User data in other tables is kept
        for audit/retention; the user simply loses access.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_users_by_status(self, status: str) -> list[dict]:
        if status not in ("pending", "approved", "rejected", "blocked"):
            raise ValueError(f"Invalid user status: {status}")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM users WHERE status = ? ORDER BY requested_at DESC",
                (status,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_all_users(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM users ORDER BY requested_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def get_admin_user_ids(self) -> list[int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT user_id FROM users WHERE is_admin = 1")
            return [row[0] for row in cursor.fetchall()]
