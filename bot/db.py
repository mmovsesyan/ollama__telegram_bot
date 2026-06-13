import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Migrate reminders table: add action column if missing
            try:
                conn.execute("ALTER TABLE reminders ADD COLUMN action TEXT DEFAULT 'notify'")
            except sqlite3.OperationalError:
                pass
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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    trigger_at TIMESTAMP,
                    recurring TEXT,
                    enabled INTEGER DEFAULT 1,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id);
                CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
            """)

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

    def disable_reminder(self, reminder_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE reminders SET enabled = 0 WHERE id = ?", (reminder_id,))
            conn.commit()

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

    def add_memory(self, user_id: int, category: str, content: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO memories (user_id, category, content) VALUES (?, ?, ?)",
                (user_id, category, content)
            )
            conn.commit()
            return cursor.lastrowid

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
