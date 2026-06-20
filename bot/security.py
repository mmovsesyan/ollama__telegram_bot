"""Access-control helpers.

Authorization now flows through the database `users` table:
- `approved` users can use the bot.
- `pending` users are waiting for admin approval.
- `rejected`/`blocked` users are denied.
- `is_admin=1` users can approve/reject/remove others.

The legacy ALLOWED_CHAT_IDS env var is used only to bootstrap the initial
admin(s) and approved users on first DB creation. After that the DB is the
source of truth.
"""

from typing import Optional

from bot.db import Database
from bot.settings import ALLOWED_CHAT_IDS

# Injected at startup by bot.__init__
db: Optional[Database] = None


def _fallback_allowed(user_id: int) -> bool:
    """Legacy env-list check used only when DB is unavailable."""
    if not ALLOWED_CHAT_IDS:
        return True
    try:
        allowed = {int(x.strip()) for x in ALLOWED_CHAT_IDS.split(",") if x.strip().isdigit()}
    except Exception:
        return False
    return user_id in allowed


def is_allowed(user_id: int) -> bool:
    """Return True if the user is approved (or no DB and env list allows)."""
    if db is None:
        return _fallback_allowed(user_id)
    return db.is_user_allowed(user_id)


def is_admin(user_id: int) -> bool:
    """Return True if the user exists and has admin privileges."""
    if db is None:
        return _fallback_allowed(user_id)
    return db.is_user_admin(user_id)
