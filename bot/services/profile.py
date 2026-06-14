"""User profile helpers: timezone + name."""

from datetime import datetime, timezone as _utc_tz
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# Country/region keyword → IANA timezone. We pick the *most populous* zone
# for multi-zone countries (Russia → Moscow, USA → New York). User can
# override via free-form input matching an IANA name.
_COUNTRY_TIMEZONES = {
    # Russia & CIS
    "россия": "Europe/Moscow",
    "russia": "Europe/Moscow",
    "москва": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "петербург": "Europe/Moscow",
    "spb": "Europe/Moscow",
    "новосибирск": "Asia/Novosibirsk",
    "екатеринбург": "Asia/Yekaterinburg",
    "владивосток": "Asia/Vladivostok",
    "калининград": "Europe/Kaliningrad",
    "беларусь": "Europe/Minsk",
    "belarus": "Europe/Minsk",
    "минск": "Europe/Minsk",
    "украина": "Europe/Kyiv",
    "ukraine": "Europe/Kyiv",
    "киев": "Europe/Kyiv",
    "kyiv": "Europe/Kyiv",
    "kiev": "Europe/Kyiv",
    "казахстан": "Asia/Almaty",
    "kazakhstan": "Asia/Almaty",
    "алматы": "Asia/Almaty",
    "almaty": "Asia/Almaty",
    "армения": "Asia/Yerevan",
    "armenia": "Asia/Yerevan",
    "ереван": "Asia/Yerevan",
    "yerevan": "Asia/Yerevan",
    "грузия": "Asia/Tbilisi",
    "georgia": "Asia/Tbilisi",
    "тбилиси": "Asia/Tbilisi",
    "tbilisi": "Asia/Tbilisi",
    "узбекистан": "Asia/Tashkent",
    "uzbekistan": "Asia/Tashkent",
    "ташкент": "Asia/Tashkent",
    "tashkent": "Asia/Tashkent",
    "азербайджан": "Asia/Baku",
    "azerbaijan": "Asia/Baku",
    "баку": "Asia/Baku",
    "baku": "Asia/Baku",
    # Western Europe
    "uk": "Europe/London",
    "великобритания": "Europe/London",
    "англия": "Europe/London",
    "england": "Europe/London",
    "london": "Europe/London",
    "лондон": "Europe/London",
    "франция": "Europe/Paris",
    "france": "Europe/Paris",
    "париж": "Europe/Paris",
    "paris": "Europe/Paris",
    "германия": "Europe/Berlin",
    "germany": "Europe/Berlin",
    "берлин": "Europe/Berlin",
    "berlin": "Europe/Berlin",
    "испания": "Europe/Madrid",
    "spain": "Europe/Madrid",
    "италия": "Europe/Rome",
    "italy": "Europe/Rome",
    "нидерланды": "Europe/Amsterdam",
    "netherlands": "Europe/Amsterdam",
    "польша": "Europe/Warsaw",
    "poland": "Europe/Warsaw",
    "португалия": "Europe/Lisbon",
    "portugal": "Europe/Lisbon",
    # Americas
    "сша": "America/New_York",
    "usa": "America/New_York",
    "us": "America/New_York",
    "америка": "America/New_York",
    "нью-йорк": "America/New_York",
    "new york": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "california": "America/Los_Angeles",
    "канада": "America/Toronto",
    "canada": "America/Toronto",
    "торонто": "America/Toronto",
    "бразилия": "America/Sao_Paulo",
    "brazil": "America/Sao_Paulo",
    # Asia/Pacific
    "китай": "Asia/Shanghai",
    "china": "Asia/Shanghai",
    "пекин": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "япония": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "токио": "Asia/Tokyo",
    "tokyo": "Asia/Tokyo",
    "индия": "Asia/Kolkata",
    "india": "Asia/Kolkata",
    "сингапур": "Asia/Singapore",
    "singapore": "Asia/Singapore",
    "австралия": "Australia/Sydney",
    "australia": "Australia/Sydney",
    "сидней": "Australia/Sydney",
    # Middle East
    "израиль": "Asia/Jerusalem",
    "israel": "Asia/Jerusalem",
    "иерусалим": "Asia/Jerusalem",
    "тель-авив": "Asia/Jerusalem",
    "tel aviv": "Asia/Jerusalem",
    "оаэ": "Asia/Dubai",
    "uae": "Asia/Dubai",
    "дубай": "Asia/Dubai",
    "dubai": "Asia/Dubai",
    "турция": "Europe/Istanbul",
    "turkey": "Europe/Istanbul",
    "стамбул": "Europe/Istanbul",
    "istanbul": "Europe/Istanbul",
}


def resolve_timezone(text: str) -> str | None:
    """Map free-form user text to an IANA timezone name.

    Tries exact IANA match first ("Europe/Moscow"), then keyword lookup
    ("Москва" → Europe/Moscow). Returns None if nothing matches.
    """
    if not text:
        return None
    cleaned = text.strip().lower()

    # Direct IANA name match (case-insensitive then case-fixed)
    for candidate in (text.strip(), text.strip().replace(" ", "_")):
        try:
            ZoneInfo(candidate)
            return candidate
        except ZoneInfoNotFoundError:
            pass

    # Keyword lookup
    if cleaned in _COUNTRY_TIMEZONES:
        return _COUNTRY_TIMEZONES[cleaned]

    # Last attempt: substring match on the keyword keys
    for keyword, tz in _COUNTRY_TIMEZONES.items():
        if keyword in cleaned:
            return tz

    return None


def get_zoneinfo(tz_name: str | None) -> ZoneInfo:
    """Safe ZoneInfo: falls back to UTC if the name is invalid or empty."""
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def now_in_tz(tz_name: str | None) -> datetime:
    return datetime.now(get_zoneinfo(tz_name))


def utc_to_local(dt_utc: datetime, tz_name: str | None) -> datetime:
    """Convert a UTC datetime to the user's local timezone."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=_utc_tz)
    return dt_utc.astimezone(get_zoneinfo(tz_name))


def local_to_utc(dt_local: datetime, tz_name: str | None) -> datetime:
    """Treat a naive datetime as being in the user's tz, return UTC."""
    if dt_local.tzinfo is None:
        dt_local = dt_local.replace(tzinfo=get_zoneinfo(tz_name))
    return dt_local.astimezone(_utc_tz)


def format_local(dt_utc: datetime, tz_name: str | None) -> str:
    """Render a UTC datetime in the user's local time, with tz suffix."""
    local = utc_to_local(dt_utc, tz_name)
    suffix = local.strftime("%Z") or tz_name or "UTC"
    return local.strftime("%Y-%m-%d %H:%M ") + suffix
