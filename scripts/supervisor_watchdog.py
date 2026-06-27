"""External watchdog: restart the bot if it dies.

This script is meant to be started once by launchd/systemd or by the Telegram
admin "supervise" command. It is NOT imported by the bot itself, so the bot
can crash without taking the watchdog down.

Usage:
    python scripts/supervisor_watchdog.py

It polls bot.pid and re-runs supervisor.start() whenever the bot disappears.
"""

import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path so we can import bot.services.supervisor.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.services.supervisor import start, stop, is_running  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
)
logger = logging.getLogger("watchdog")

CHECK_INTERVAL = 10


def main() -> None:
    if os.environ.get("BOT_WATCHDOG") == "1":
        logger.error("Detected nested watchdog; aborting to avoid fork bomb.")
        sys.exit(1)

    os.environ["BOT_WATCHDOG"] = "1"
    logger.info("Watchdog started. Root: %s", ROOT)

    while True:
        if not is_running():
            logger.warning("Bot not running; restarting...")
            ok, msg = start()
            if not ok:
                logger.error("Restart failed: %s", msg)
                time.sleep(30)
                continue
            logger.info("Restart succeeded: %s", msg)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Stopping watchdog and bot...")
        stop()
        sys.exit(0)
