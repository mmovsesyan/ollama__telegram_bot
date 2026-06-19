"""Retention policy: clean up old documents, images, and optionally memories.

Runs daily via APScheduler. Per-user retention_days from user_prefs controls
the cutoff; None/0 means "keep forever". Memories are never auto-deleted
because they form the long-term knowledge base.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

db: Any = None  # injected at startup by bot.__init__

DEFAULT_RETENTION_DAYS = 90


def _utc_cutoff(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat()


def _unlink_safely(path: str | None) -> None:
    if not path:
        return
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
            logger.debug("[RETENTION] removed file %s", path)
    except Exception as e:
        logger.warning("[RETENTION] failed to remove file %s: %s", path, e)


def cleanup_user_retention(user_id: int) -> tuple[int, int]:
    """Delete documents and images older than the user's retention_days.

    Returns (docs_removed, images_removed).
    """
    if db is None:
        return 0, 0
    try:
        prefs = db.get_user_prefs(user_id) or {}
    except Exception as e:
        logger.warning("[RETENTION] failed to load prefs for %s: %s", user_id, e)
        return 0, 0

    days = prefs.get("retention_days")
    if days is None or days == 0:
        return 0, 0
    days = max(1, int(days))
    cutoff = _utc_cutoff(days)

    removed_docs = 0
    try:
        old_docs = db.get_old_documents(cutoff)
        for doc in old_docs:
            if doc.get("user_id") != user_id:
                continue
            _unlink_safely(doc.get("local_path"))
        removed_docs = db.cleanup_old_documents(cutoff)
    except Exception as e:
        logger.warning("[RETENTION] document cleanup failed for %s: %s", user_id, e)

    removed_images = 0
    try:
        old_images = db.get_old_images(cutoff)
        for img in old_images:
            if img.get("user_id") != user_id:
                continue
            _unlink_safely(img.get("local_path"))
        removed_images = db.cleanup_old_images(cutoff)
    except Exception as e:
        logger.warning("[RETENTION] image cleanup failed for %s: %s", user_id, e)

    logger.info(
        "[RETENTION] user_id=%s days=%s docs=%s images=%s",
        user_id,
        days,
        removed_docs,
        removed_images,
    )
    return removed_docs, removed_images


def cleanup_all_retention() -> tuple[int, int]:
    """Run retention cleanup for every user. Returns total (docs, images)."""
    if db is None:
        return 0, 0
    try:
        user_ids = db.get_all_user_ids()
    except Exception as e:
        logger.warning("[RETENTION] failed to list users: %s", e)
        return 0, 0

    total_docs = 0
    total_images = 0
    for user_id in user_ids:
        d, i = cleanup_user_retention(user_id)
        total_docs += d
        total_images += i
    return total_docs, total_images
