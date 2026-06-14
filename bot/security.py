from bot.settings import ALLOWED_CHAT_IDS


def is_allowed(user_id: int) -> bool:
    """Return True if the user is authorized or no allow-list is configured."""
    if not ALLOWED_CHAT_IDS:
        return True
    allowed = {int(x.strip()) for x in ALLOWED_CHAT_IDS.split(",") if x.strip().isdigit()}
    return user_id in allowed
