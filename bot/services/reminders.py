import re
from datetime import datetime, timedelta, timezone

from bot.keyboards.reply import command_keyboard

db = None  # injected from bot.__init__


def _time_from_period_word(word: str | None) -> tuple[int, int]:
    """Map fuzzy period words to a default time of day."""
    if not word:
        return 9, 0
    w = word.lower().strip()
    if "утр" in w or w == "утром":
        return 8, 0
    if w in ("днём", "днем", "день", "дня"):
        return 13, 0
    if w in ("вечер", "вечером", "вечера"):
        return 19, 0
    if w in ("ночь", "ночью"):
        return 23, 0
    return 9, 0


def _extract_time_of_day(text: str) -> tuple[int, int] | None:
    """Look for explicit HH:MM, bare hour after 'в', or fuzzy words like утром/днём/вечером/ночью."""
    m = re.search(r'(\d{1,2}):(\d{2})', text)
    if m:
        h = max(0, min(23, int(m.group(1))))
        minute = max(0, min(59, int(m.group(2))))
        return h, minute
    m = re.search(r'\bв\s+(\d{1,2})(?::(\d{2}))?\b', text)
    if m:
        h = max(0, min(23, int(m.group(1))))
        minute = max(0, min(59, int(m.group(2) or 0)))
        return h, minute
    if re.search(r'\b7\s*утра\b|\b07\s*утра\b', text):
        return 7, 0
    if re.search(r'\b9\s*утра\b|\b09\s*утра\b', text):
        return 9, 0
    if re.search(r'\b12\s*дня\b|\b12\s*дн[яе]\b', text):
        return 12, 0
    if re.search(r'\b15\s*дня\b|\b15\s*дн[яе]\b', text):
        return 15, 0
    if re.search(r'\bутр(ом|а)\b', text):
        return 8, 0
    if re.search(r'\bдн(ём|ем|я)\b', text):
        return 13, 0
    if re.search(r'\bвечер(ом|а)\b', text):
        return 19, 0
    if re.search(r'\bноч(ью|и)\b', text):
        return 23, 0
    return None


# Shared regex fragments for fuzzy Russian time strings.
_TIME_MODIFIERS = r'(утра|утром|дня|днём|днем|вечера|вечером|ночи|ночью)'
_TIME_RE = r'\d{1,2}(?::\d{2})?(?:\s+' + _TIME_MODIFIERS + r')?'

_MINUTE_UNITS = r'(?:минут(?:ы|у)?|мин)'
_HOUR_UNITS = r'(?:час(?:ов|а)?|ч)'
_DAY_UNITS = r'(?:дн(?:ей|я|ь)|д)'
_WEEK_UNITS = r'(?:недел(?:ь|и|ю))'
_MONTH_UNITS = r'(?:месяц(?:ев|а)?)'


def _extract_time_string(text: str) -> str | None:
    """Return the scheduling/time substring so it can be stripped from content."""
    lowered = text.lower().strip()

    def _match(pattern: str) -> str | None:
        m = re.search(pattern, lowered, re.IGNORECASE)
        if m and m.group(0).strip():
            start, end = m.span()
            return text[start:end].strip()
        return None

    # 1. Recurring: daily / every morning/evening/night / по календарю
    p = _match(
        r'(?:ежедневно|каждый\s+день|every\s+day|daily|по\s+календарю|'
        r'каждое\s+утро|каждое\s+утра|каждый\s+вечер|каждый\s+вечера|'
        r'каждую\s+ночь|каждую\s+ночи|каждое\s+дн[яе])'
        r'(?:\s+в\s+' + _TIME_RE + r')?'
        r'(?:\s+' + _TIME_RE + r')?'
    )
    if p:
        return p

    # 2. Weekday
    p = _match(
        r'(?:каждый\s+будний\s+день|каждый\s+будний|будни(?:е)?|'
        r'рабочие\s+дни|каждый\s+рабочий\s+день?|weekday|по\s+будням)'
        r'(?:\s+в\s+' + _TIME_RE + r')?'
        r'(?:\s+' + _TIME_RE + r')?'
    )
    if p:
        return p

    # 3. Weekend
    p = _match(
        r'(?:каждый\s+выходной|выходные|weekend|по\s+выходным)'
        r'(?:\s+в\s+' + _TIME_RE + r')?'
        r'(?:\s+' + _TIME_RE + r')?'
    )
    if p:
        return p

    # 4. Weekly (optionally with a day-of-week and time)
    p = _match(
        r'(?:еженедельно|every\s+week|weekly|каждую\s+неделю)'
        r'(?:\s+в\s+(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье))?'
        r'(?:\s+в\s+' + _TIME_RE + r')?'
        r'(?:\s+' + _TIME_RE + r')?'
    )
    if p:
        return p

    # 5. Monthly
    p = _match(
        r'(?:ежемесячно|every\s+month|monthly|каждый\s+месяц)'
        r'(?:\s+в\s+' + _TIME_RE + r')?'
        r'(?:\s+' + _TIME_RE + r')?'
    )
    if p:
        return p

    # 6. Day-of-week absolute
    p = _match(
        r'(?:(?:в\s+)?(?:понедельник|вторник|среду|четверг|пятницу|субботу|'
        r'воскресенье|monday|tuesday|wednesday|thursday|friday|saturday|sunday))'
        r'(?:\s+в\s+' + _TIME_RE + r')?'
        r'(?:\s+' + _TIME_RE + r')?'
    )
    if p:
        return p

    # 7. Every N minutes/hours/days/weeks/months
    p = _match(
        r'(?:каждые|раз\s+в)\s+\d+\s*(?:' + _MINUTE_UNITS + '|' + _HOUR_UNITS + '|' +
        _DAY_UNITS + '|' + _WEEK_UNITS + '|' + _MONTH_UNITS + r')?'
        r'(?:\s+' + _TIME_RE + r')?'
    )
    if p:
        return p

    # 8. Relative offsets: через N ... / через неделю / через месяц
    p = _match(
        r'через\s+(?:(?:\d+)\s*(?:' + _MINUTE_UNITS + '|' + _HOUR_UNITS + '|' +
        _DAY_UNITS + '|' + _WEEK_UNITS + '|' + _MONTH_UNITS + r')|' +
        _WEEK_UNITS + '|' + _MONTH_UNITS + r')'
        r'(?:\s+' + _TIME_RE + r')?'
    )
    if p:
        return p

    # 9. Today / tomorrow: "завтра в 9:00", "завтра 9:00", "завтра днем",
    #    "9:00 утра завтра", bare "завтра"
    p = _match(
        rf'(?:сегодня|завтра)\s+в\s+{_TIME_RE}?'
        rf'|(?:сегодня|завтра)\s+{_TIME_RE}'
        rf'|(?:сегодня|завтра)\s+(?:{_TIME_MODIFIERS})'
        rf'|(?:{_TIME_RE}\s+)?(?:сегодня|завтра)'
    )
    if p:
        return p

    # 10. Bare ISO datetime
    p = _match(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}')
    if p:
        return p

    # 11. Bare time
    p = _match(r'(?:в\s+)?' + _TIME_RE)
    if p:
        return p

    return None


def parse_time(text: str) -> datetime:
    dt, _ = parse_reminder(text)
    return dt


def parse_reminder(text: str) -> tuple[datetime, str | None]:
    """Parse reminder time. Returns (datetime, recurrence_pattern).
    recurrence_pattern: daily, weekday, weekend, weekly, monthly,
                        monday..sunday, or None."""
    now = datetime.now(timezone.utc)
    lowered = text.lower().strip()
    recurrence = None

    h, m = _extract_time_of_day(lowered) or (9, 0)

    # --- Recurring patterns ---------------------------------------------
    if re.search(
        r'ежедневно|каждый\s+день|every\s+day|daily|по\s+календарю|'
        r'каждое\s+утро|каждое\s+утра|каждый\s+вечер|каждый\s+вечера|'
        r'каждую\s+ночь|каждую\s+ночи|каждое\s+дн[яе]',
        lowered,
    ):
        recurrence = "daily"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, recurrence

    if re.search(r'каждый\s+будний|будни(е)?|рабочие\s+дни|каждый\s+рабочий|weekday|по\s+будням', lowered):
        recurrence = "weekday"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now or target.weekday() >= 5:
            target += timedelta(days=1)
            while target.weekday() >= 5:
                target += timedelta(days=1)
        return target, recurrence

    if re.search(r'каждый\s+выходной|выходные|weekend|по\s+выходным', lowered):
        recurrence = "weekend"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now or target.weekday() < 5:
            target += timedelta(days=1)
            while target.weekday() < 5:
                target += timedelta(days=1)
        return target, recurrence

    if re.search(r'еженедельно|every\s+week|weekly|каждую\s+неделю', lowered):
        recurrence = "weekly"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(weeks=1)
        return target, recurrence

    if re.search(r'ежемесячно|every\s+month|monthly|каждый\s+месяц', lowered):
        recurrence = "monthly"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        # Approximate monthly: 30 days from now
        return target + timedelta(days=30), recurrence

    # --- Every N minutes/hours/days/weeks/months --------------------------
    interval_match = re.search(
        r'(каждые|раз\s+в)\s+(\d+)\s*(' + _MINUTE_UNITS + '|' + _HOUR_UNITS + '|' +
        _DAY_UNITS + '|' + _WEEK_UNITS + '|' + _MONTH_UNITS + r')?',
        lowered,
    )
    if interval_match:
        num = int(interval_match.group(2))
        unit_raw = (interval_match.group(3) or "").lower()
        if re.search(_MINUTE_UNITS, unit_raw):
            return now + timedelta(minutes=num), None
        if re.search(_HOUR_UNITS, unit_raw):
            return now + timedelta(hours=num), None
        if re.search(_DAY_UNITS, unit_raw):
            return now + timedelta(days=num), None
        if re.search(_WEEK_UNITS, unit_raw):
            return now + timedelta(weeks=num), None
        if re.search(_MONTH_UNITS, unit_raw):
            return now + timedelta(days=30 * num), None
        # default to minutes when unit omitted
        return now + timedelta(minutes=num), None

    # --- Day-of-week patterns -------------------------------------------
    weekday_map = {
        "понедельник": "monday", "monday": "monday",
        "вторник": "tuesday", "tuesday": "tuesday",
        "среда": "wednesday", "wednesday": "wednesday",
        "четверг": "thursday", "thursday": "thursday",
        "пятница": "friday", "friday": "friday",
        "суббота": "saturday", "saturday": "saturday",
        "воскресенье": "sunday", "sunday": "sunday",
    }
    for day_word, day_key in weekday_map.items():
        if day_word in lowered:
            recurrence = day_key
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            target_weekday = target.weekday()
            day_num = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}[day_key]
            if target_weekday != day_num or target <= now:
                days_ahead = (day_num - target_weekday) % 7
                if days_ahead == 0:
                    days_ahead = 7
                target += timedelta(days=days_ahead)
            return target, recurrence

    # --- Relative offsets -----------------------------------------------
    # через неделю / через месяц (no digit)
    if re.search(r'через\s+' + _WEEK_UNITS, lowered):
        return now + timedelta(weeks=1), None
    if re.search(r'через\s+' + _MONTH_UNITS, lowered):
        return now + timedelta(days=30), None

    through_match = re.search(
        r'через\s+(\d+)\s*(' + _MINUTE_UNITS + '|' + _HOUR_UNITS + '|' +
        _DAY_UNITS + '|' + _WEEK_UNITS + '|' + _MONTH_UNITS + r')?',
        lowered,
    )
    if through_match:
        num = int(through_match.group(1))
        unit = (through_match.group(2) or "").lower()
        if re.search(_MINUTE_UNITS, unit):
            return now + timedelta(minutes=num), None
        if re.search(_HOUR_UNITS, unit):
            return now + timedelta(hours=num), None
        if re.search(_DAY_UNITS, unit):
            return now + timedelta(days=num), None
        if re.search(_WEEK_UNITS, unit):
            return now + timedelta(weeks=num), None
        if re.search(_MONTH_UNITS, unit):
            return now + timedelta(days=30 * num), None
        return now + timedelta(minutes=num), None

    # --- Today / tomorrow -----------------------------------------------
    today_match = re.search(r'сегодня\s+в\s+(\d{1,2}):(\d{2})', lowered)
    if today_match:
        h = max(0, min(23, int(today_match.group(1))))
        m = max(0, min(59, int(today_match.group(2))))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, None

    if "сегодня" in lowered:
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, None

    if "завтра" in lowered:
        time_match = re.search(r'(\d{1,2}):(\d{2})', lowered)
        if time_match:
            h = max(0, min(23, int(time_match.group(1))))
            m = max(0, min(59, int(time_match.group(2))))
        target = (now + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
        return target, None

    # --- ISO datetime ---------------------------------------------------
    try:
        dt = datetime.fromisoformat(lowered)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, None
    except Exception:
        pass

    return now + timedelta(minutes=5), None


async def _process_remind(user_id: int, text: str, action: str = "notify"):
    if db is None:
        from bot.bot import bot as aiogram_bot
        await aiogram_bot.send_message(chat_id=user_id, text="База данных недоступна.", reply_markup=command_keyboard)
        return

    trigger_at, recurring = parse_reminder(text)
    time_str = _extract_time_string(text)
    content = text.replace(time_str, "").strip() if time_str else text
    content = re.sub(r"\s+", " ", content).strip(",. ")

    if not trigger_at:
        trigger_at = datetime.now(timezone.utc) + timedelta(hours=1)

    reminder_id = db.add_reminder(
        user_id=user_id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action=action,
    )

    rec_label = f" ({recurring})" if recurring else ""

    from bot.bot import bot as aiogram_bot
    await aiogram_bot.send_message(
        chat_id=user_id,
        text=f"✅ Напоминание #{reminder_id} добавлено\n"
             f"🕐 Сработает: {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
             f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )


async def _process_task_from_text(user_id: int, text: str):
    """Free-form task: parse time, strip it from content, schedule AI execution."""
    if db is None:
        from bot.bot import bot as aiogram_bot
        await aiogram_bot.send_message(chat_id=user_id, text="База данных недоступна.", reply_markup=command_keyboard)
        return

    trigger_at, recurring = parse_reminder(text)
    time_str = _extract_time_string(text)
    content = text.replace(time_str, "").strip() if time_str else text
    content = re.sub(r"\s+", " ", content).strip(",. ")

    if not trigger_at:
        trigger_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    rid = db.add_reminder(
        user_id=user_id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="execute",
    )
    rec_label = f" ({recurring})" if recurring else ""
    from bot.bot import bot as aiogram_bot
    await aiogram_bot.send_message(
        chat_id=user_id,
        text=f"✅ Задача #{rid} добавлена\n"
             f"🕐 Сработает: {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
             f"🤖 Режим: AI-выполнение\n"
             f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )
