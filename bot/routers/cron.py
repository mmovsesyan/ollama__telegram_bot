from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import re
import json
from datetime import datetime, timedelta, timezone

import aiohttp

from bot.states import BotStates
from bot.keyboards.reply import command_keyboard, cancel_keyboard, fsm_keyboard
from bot.keyboards.inline import (
    confirm_keyboard,
    memory_category_keyboard,
    recurring_suggest_keyboard,
    reminder_quick_keyboard,
)
from bot.settings import ALLOWED_CHAT_IDS

router = Router()

db = None  # injected in __init__

# Known command buttons that should cancel pending FSM input
_COMMAND_BUTTONS = {
    "💬 Чат", "🔍 Поиск", "⏰ Напоминание", "🧠 Память",
    "❓ Помощь", "🗑 Очистить",
}


# Button text → handler mapping for instant routing when pressed during FSM
_BUTTON_HANDLERS: dict[str, callable] = {}


async def _fsm_guard(message: Message, state: FSMContext) -> bool:
    """If user sends a cancel/command while in FSM state, cancel state and return True."""
    text = message.text or ""

    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())
        return True

    if text in _COMMAND_BUTTONS:
        await state.clear()
        handler = _BUTTON_HANDLERS.get(text)
        if handler:
            await handler(message, state)
        else:
            await message.answer(
                "Текущее действие отменено. Нажмите кнопку ещё раз.",
            )
        return True

    if text.startswith("/"):
        await state.clear()
        await message.answer(
            "Текущее действие отменено. Введите команду повторно.",
        )
        return True

    return False


def _is_allowed(user_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    allowed = {int(x.strip()) for x in ALLOWED_CHAT_IDS.split(",") if x.strip().isdigit()}
    return user_id in allowed


# --- Monitor helpers ---
def _parse_interval(text: str) -> int:
    """Parse interval: 5m, 10m, 1h, 2h, or raw seconds. Default 300 (5 min)."""
    text = text.strip().lower()
    if not text:
        return 300
    if text.endswith('m'):
        try:
            return int(text[:-1]) * 60
        except ValueError:
            return 300
    if text.endswith('h'):
        try:
            return int(text[:-1]) * 3600
        except ValueError:
            return 300
    try:
        return int(text)
    except ValueError:
        return 300


def _format_interval(seconds: int) -> str:
    """Format seconds to human readable."""
    if seconds < 60:
        return f"{seconds} сек"
    if seconds < 3600:
        return f"{seconds // 60} мин"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if m == 0:
        return f"{h} ч"
    return f"{h} ч {m} мин"


def _normalize_url(url: str) -> str:
    """Add http:// if no scheme present."""
    url = url.strip()
    if '://' not in url:
        url = f"http://{url}"
    return url
# --- End monitor helpers ---

import html


def _clean_snippet(text: str, max_len: int = 200) -> str:
    """Aggressively clean a web-search content snippet for Telegram display."""
    if not text:
        return ""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Collapse all whitespace into a single space
    text = re.sub(r"\s+", " ", text).strip()

    # Drop obvious garbage / e-commerce / navigation fragments
    garbage = [
        r"В приложении удобнее",
        r"RuStore",
        r"Samsung Galaxy Store",
        r"Huawei AppGallery",
        r"Xiaomi GetApps",
        r"AppGallery",
        r"GetApps",
        r"КУПИТЬ",
        r"ДОСТАВКА",
        r"СПОСОБЫ",
        r"отслеживать",
        r"Сравнить",
        r"В список желаний",
        r"Сделать любимым",
        r"Оставить отзыв",
        r"Подробнее",
        r"ПОДРОБНЕЕ",
        r"рейтинг:",
        r"\(1\)",
        r"ISBN",
        r"Артикул",
        r"Артикул:",
        r"товара:",
        r"Попробуйте обновленную версию",
        r"LiveLib",
        r"Часть функций",
        r"бета-версии",
        r"Моя оценка",
        r"Все уведомления",
        r"Рецензии",
        r"Цитаты",
        r"Издания и произведения",
        r"Пожаловаться",
        r"прочитали",
        r"планируют",
        r"рецензий",
        r"цитаты",
        r"№\d+ в ",
        r"Goodreads",
        r"Вподобайки",
        r"Характеристики",
        r"Переглянути фото",
        r"Паперова",
        r"Електронна",
        r"В наявності",
        r"Відправка:",
        r"Не получается оформить заказ?",
        r"укажите код",
        r"СПОСОБЫ ОПЛАТЫ",
        r"код \d+",
        r"КУПИТЬ С ДОСТАВКОЙ",
        r"книгу в наявності",
    ]
    for g in garbage:
        text = re.sub(g, "", text, flags=re.IGNORECASE)
    # Collapse again after deletions
    text = re.sub(r"\s+", " ", text).strip()
    # Take first 2 sentences (split on .!? followed by space or end)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences:
        snippet = sentences[0]
        if len(snippet) < 60 and len(sentences) > 1:
            snippet += " " + sentences[1]
    else:
        snippet = text
    # Final hard truncate to max_len, break at last space
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rsplit(" ", 1)[0] + "..."
    return snippet.strip()


def _extract_main_text(html_text: str, max_len: int = 250) -> str:
    """Use BeautifulSoup to strip nav/scripts and extract the longest coherent paragraph."""
    try:
        from bs4 import BeautifulSoup
    except Exception:
        # Fallback if bs4 is missing
        return _clean_snippet(html_text, max_len)

    soup = BeautifulSoup(html_text, "lxml")
    # Remove non-content tags
    for tag_name in ("script", "style", "nav", "header", "footer", "aside", "form", "button", "noscript"):
        for t in soup.find_all(tag_name):
            t.decompose()
    # Prefer meta description
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
        if 30 < len(desc) < 300:
            return desc[:max_len].rsplit(" ", 1)[0] + "..." if len(desc) > max_len else desc

    # Collect all paragraph-like blocks and pick the longest coherent one
    candidates = []
    for tag in soup.find_all(("p", "div", "article", "section", "span")):
        txt = tag.get_text(separator=" ", strip=True)
        # Skip tiny fragments and obvious non-content
        if len(txt) < 30:
            continue
        # Penalize fragments with lots of pipes, arrows, menu-like punctuation
        noise = txt.count("|") + txt.count("→") + txt.count("↳") + txt.count("▸") + txt.count("·")
        score = len(txt) - noise * 10
        candidates.append((score, txt))
    if not candidates:
        return _clean_snippet(html_text, max_len)
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    # Limit to first meaningful paragraph (stop at double newline if any)
    best = best.replace("\n\n", "\n").split("\n")[0]
    if len(best) > max_len:
        best = best[:max_len].rsplit(" ", 1)[0] + "..."
    return best.strip()


async def ollama_web_search(query: str, max_results: int = 5):
    from bot.settings import OLLAMA_WEB_API_KEY
    if not OLLAMA_WEB_API_KEY:
        return None, "OLLAMA_WEB_API_KEY не установлен. Получите ключ на https://ollama.com"

    url = "https://ollama.com/api/web_search"
    headers = {
        "Authorization": f"Bearer {OLLAMA_WEB_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "max_results": max_results}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                text = await resp.text()
                if resp.status == 200:
                    try:
                        data = json.loads(text)
                        return data, None
                    except json.JSONDecodeError as e:
                        return None, f"JSON decode error: {e}"
                else:
                    return None, f"HTTP {resp.status}: {text[:200]}"
    except Exception as e:
        return None, str(e)


async def ollama_web_fetch(url: str):
    from bot.settings import OLLAMA_WEB_API_KEY
    if not OLLAMA_WEB_API_KEY:
        return None, "OLLAMA_WEB_API_KEY не установлен. Получите ключ на https://ollama.com"

    api_url = "https://ollama.com/api/web_fetch"
    headers = {
        "Authorization": f"Bearer {OLLAMA_WEB_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"url": url}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                text = await resp.text()
                if resp.status == 200:
                    try:
                        data = json.loads(text)
                        return data, None
                    except json.JSONDecodeError as e:
                        return None, f"JSON decode error: {e}"
                else:
                    return None, f"HTTP {resp.status}: {text[:200]}"
    except Exception as e:
        return None, str(e)


async def send_alert(user_id: int, text: str):
    from bot.bot import bot as aiogram_bot
    try:
        await aiogram_bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        print(f"[ALERT] Failed to send to {user_id}: {e}")

def parse_time(text: str) -> datetime:
    dt, _ = parse_reminder(text)
    return dt


def parse_reminder(text: str) -> tuple[datetime, str | None]:
    """Parse reminder time. Returns (datetime, recurrence_pattern).
    recurrence_pattern: daily, weekday, weekend, weekly, monday..sunday, or None."""
    from datetime import timezone
    now = datetime.now(timezone.utc)
    text = text.lower().strip()
    recurrence = None

    # Extract time from text (default 9:00)
    def _extract_time(txt: str) -> tuple[int, int]:
        m = re.search(r'(\d{1,2}):(\d{2})', txt)
        if m:
            return int(m.group(1)), int(m.group(2))
        if re.search(r'\b7\s*утра\b|\b07\s*утра\b', txt):
            return 7, 0
        if re.search(r'\b9\s*утра\b|\b09\s*утра\b', txt):
            return 9, 0
        if re.search(r'\b12\s*дня\b|\b12\s*дн[яе]\b', txt):
            return 12, 0
        if re.search(r'\b15\s*дня\b|\b15\s*дн[яе]\b', txt):
            return 15, 0
        return 9, 0

    h, m = _extract_time(text)

    # --- Recurring patterns ---
    # every day / daily / ежедневно / каждый день
    if re.search(r'ежедневно|каждый\s+день|every\s+day|daily', text):
        recurrence = "daily"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, recurrence

    # every weekday / будний день
    if re.search(r'каждый\s+будний|будние|каждый\s+рабочий|weekday|по\s+будням', text):
        recurrence = "weekday"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now or target.weekday() >= 5:
            target += timedelta(days=1)
            while target.weekday() >= 5:
                target += timedelta(days=1)
        return target, recurrence

    # weekend / выходной
    if re.search(r'каждый\s+выходной|выходные|weekend', text):
        recurrence = "weekend"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now or target.weekday() < 5:
            target += timedelta(days=1)
            while target.weekday() < 5:
                target += timedelta(days=1)
        return target, recurrence

    # weekly / еженедельно
    if re.search(r'еженедельно|every\s+week|weekly|каждую\s+неделю', text):
        recurrence = "weekly"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(weeks=1)
        return target, recurrence

    # Specific days
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
        if day_word in text:
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

    # через N минут / часов / дней / м / ч / д
    if text.startswith("через"):
        match = re.search(r'\d+', text)
        if match:
            num = int(match.group())
            if re.search(r'минут|мин|м(?![а-я])', text):
                return now + timedelta(minutes=num), None
            if re.search(r'час|ч(?![а-я])', text):
                return now + timedelta(hours=num), None
            if re.search(r'день|дня|дней|д(?![а-я])', text):
                return now + timedelta(days=num), None

    # сегодня в HH:MM
    today_match = re.search(r'сегодня\s+в\s+(\d{1,2}):(\d{2})', text)
    if today_match:
        h, m = int(today_match.group(1)), int(today_match.group(2))
        return now.replace(hour=h, minute=m, second=0, microsecond=0), None

    # завтра [в HH:MM]
    if "завтра" in text:
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=h, minute=m, second=0, microsecond=0), None

    try:
        return datetime.fromisoformat(text), None
    except:
        pass

    return now + timedelta(minutes=5), None

@router.message(lambda m: m.text and (m.text == "/remind" or m.text.startswith("/remind ")))
async def cmd_remind(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "⏰ Чего напомнить?\n"
            "Например: позвонить брокеру",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_remind)
        return

    await _process_remind(message.from_user.id, parts[1])


@router.message(F.text == "⏰ Напоминание")
async def btn_remind(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    await message.answer(
        "⏰ Чего напомнить?\n"
        "Например: позвонить брокеру",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_remind)


async def _process_remind(user_id: int, text: str, action: str = "notify"):
    trigger_at, recurring = parse_reminder(text)

    # Strip the time portion from the beginning to get the reminder content
    time_patterns = [
        r"^(через \d+ (?:минут|час|день|дней|дня))",
        r"^(завтра в \d{1,2}:\d{2})",
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
        r"^(\d{2}:\d{2})",
    ]

    content = text
    for pattern in time_patterns:
        match = re.match(pattern, text)
        if match:
            time_str = match.group(1)
            content = text[len(time_str):].strip()
            break

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
        text=f"⏰ Напоминание #{reminder_id} установлено на {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
             f"Текст: {content}",
    )


@router.message(BotStates.waiting_remind)
async def process_remind(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    content = message.text.strip()
    if not content:
        await message.answer("Введите текст напоминания.", reply_markup=cancel_keyboard)
        return
    await state.update_data(remind_content=content)
    await state.set_state(BotStates.waiting_remind_time)
    await message.answer(
        f"⏰ Напомнить: {content}\n\nКогда?",
        reply_markup=reminder_quick_keyboard(),
    )


@router.callback_query(F.data.startswith("remind_quick:"))
async def cb_remind_quick(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    mode = callback.data.split(":", 1)[1]
    data = await state.get_data()
    content = data.get("remind_content", "")
    if not content:
        await callback.answer("Ошибка: нет текста", show_alert=True)
        await state.clear()
        return

    now = datetime.now(timezone.utc)
    trigger_at = now
    recurring = None

    if mode == "5m":
        trigger_at = now + timedelta(minutes=5)
    elif mode == "tomorrow9":
        trigger_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif mode == "daily9":
        trigger_at = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if trigger_at <= now:
            trigger_at += timedelta(days=1)
        recurring = "daily"
    elif mode == "auto":
        await state.set_state(BotStates.waiting_remind_time)
        await callback.message.answer(
            "⏰ Когда напомнить?\n"
            "Например: через 5 минут, завтра в 9:00, каждый день в 7:00",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Введите время")
        return
    else:
        trigger_at = now + timedelta(minutes=5)

    rid = db.add_reminder(
        user_id=callback.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="notify",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await callback.message.answer(
        f"✅ Напоминание #{rid} установлено на {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
        f"Текст: {content}",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()
    await callback.answer("Напоминание создано")


@router.message(BotStates.waiting_remind_time)
async def process_remind_time(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    data = await state.get_data()
    content = data.get("remind_content", "")
    if not content:
        await message.answer("Ошибка: не найден текст напоминания.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    time_text = message.text.strip()
    trigger_at, recurring = parse_reminder(time_text)
    rid = db.add_reminder(
        user_id=message.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="notify",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await message.answer(
        f"✅ Напоминание #{rid} установлено на {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
        f"Текст: {content}",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()

@router.message(lambda m: m.text and m.text == "/reminders")
async def cmd_reminders(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    reminders = db.get_user_reminders(message.from_user.id)
    if not reminders:
        await message.answer(
            "Нет активных напоминаний.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить напоминание", callback_data="add_reminder")]]
            ),
        )
        await message.answer("Выберите действие:")
        return

    text = "⏰ Активные напоминания:\n\n"
    buttons = []
    for idx, r in enumerate(reminders, 1):
        time_str = r.get('trigger_at', 'ASAP')
        content = r.get('content', '')
        rec = r.get('recurring')
        mode = "🤖" if r.get('action') == 'execute' else "⏰"
        rec_label = f" ({rec})" if rec else ""
        text += f"#{idx} {mode} | {time_str}{rec_label}\n{content}\n\n"
        buttons.append([InlineKeyboardButton(text=f"❌ Удалить #{idx}", callback_data=f"del_reminder:{r['id']}")])

    buttons.append([InlineKeyboardButton(text="➕ Добавить напоминание", callback_data="add_reminder")])
    await message.answer(text.strip(), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await message.answer("Выберите действие:")

@router.message(lambda m: m.text and m.text.startswith("/remind_cancel"))
async def cmd_remind_cancel(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "❌ Введите ID напоминания для отмены:\n"
            "Пример: 3",
        )
        await state.set_state(BotStates.waiting_remind_cancel)
        return

    try:
        rid = int(parts[1])
        user_reminders = db.get_user_reminders(message.from_user.id)
        if not any(r['id'] == rid for r in user_reminders):
            await message.answer("Нет доступа к этому напоминанию.")
            return
        db.disable_reminder(rid)
        await message.answer(f"Напоминание #{rid} отменено.")
    except ValueError:
        await message.answer("Укажите числовой ID напоминания.")


@router.message(BotStates.waiting_remind_cancel)
async def process_remind_cancel(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    try:
        rid = int(message.text.strip())
        user_reminders = db.get_user_reminders(message.from_user.id)
        if not any(r['id'] == rid for r in user_reminders):
            await message.answer("Нет доступа к этому напоминанию.", reply_markup=cancel_keyboard)
            await state.clear()
            return
        db.disable_reminder(rid)
        await message.answer(f"Напоминание #{rid} отменено.", reply_markup=cancel_keyboard)
    except ValueError:
        await message.answer("Укажите числовой ID напоминания.", reply_markup=cancel_keyboard)
    await state.clear()

@router.message(lambda m: m.text and m.text.startswith("/note"))
async def cmd_note(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        notes = db.get_notes(message.from_user.id)
        if notes:
            await message.answer(f"📝 Твои заметки:\n{notes}")
        else:
            await message.answer(
                "📝 Введите текст заметки:\n"
                "Пример: купить акции TSLA",
            )
            await state.set_state(BotStates.waiting_note)
        return

    db.add_note(message.from_user.id, parts[1])
    await message.answer("Заметка сохранена. AI будет помнить это.")


@router.message(F.text == "📝 Заметка")
async def btn_note(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return
    notes = db.get_notes(message.from_user.id)
    if notes:
        await message.answer(f"📝 Твои заметки:\n{notes}")
    else:
        await message.answer(
            "📝 Введите текст заметки:\n"
            "Пример: купить акции TSLA",
        )
        await state.set_state(BotStates.waiting_note)


@router.message(BotStates.waiting_note)
async def process_note(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    db.add_note(message.from_user.id, message.text)
    await message.answer("Заметка сохранена. AI будет помнить это.", reply_markup=cancel_keyboard)
    await state.clear()

@router.message(lambda m: m.text and m.text.startswith("/monitor_add"))
async def cmd_monitor_add(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) >= 3:
        await _process_monitor_add(
            message,
            parts[1],
            _normalize_url(parts[2]),
            _parse_interval(parts[3]) if len(parts) >= 4 else 300,
        )
        return

    await message.answer(
        "🔍 Название монитора?\n"
        "Например: Google",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_monitor_name)


@router.message(BotStates.waiting_monitor_name)
async def process_monitor_name(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    name = message.text.strip()
    if not name:
        await message.answer("Введите название монитора.", reply_markup=cancel_keyboard)
        return
    await state.update_data(monitor_name=name)
    await state.set_state(BotStates.waiting_monitor_url)
    await message.answer(
        f"🔍 Монитор: {name}\n\nВведите URL:\n"
        "Например: google.com или https://google.com",
        reply_markup=cancel_keyboard,
    )


@router.message(BotStates.waiting_monitor_url)
async def process_monitor_url(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    url = _normalize_url(message.text.strip())
    if not url:
        await message.answer("Введите URL.", reply_markup=cancel_keyboard)
        return
    await state.update_data(monitor_url=url)
    await state.set_state(BotStates.waiting_monitor_interval)
    await message.answer(
        "🔍 Интервал проверки?\n"
        "Например: 5m, 1h, или 300 (секунд)",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="5 минут", callback_data="mon_int:5m")],
                [InlineKeyboardButton(text="15 минут", callback_data="mon_int:15m")],
                [InlineKeyboardButton(text="1 час", callback_data="mon_int:1h")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("mon_int:"))
async def cb_monitor_interval(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    interval_text = callback.data.split(":", 1)[1]
    await state.update_data(monitor_interval=_parse_interval(interval_text))
    await _finish_monitor_add(callback.message, state, callback.from_user.id)
    await callback.answer("Монитор добавлен")


@router.message(BotStates.waiting_monitor_interval)
async def process_monitor_interval(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    interval = _parse_interval(message.text.strip())
    await state.update_data(monitor_interval=interval)
    await _finish_monitor_add(message, state, message.from_user.id)


async def _finish_monitor_add(message: Message, state: FSMContext, user_id: int):
    data = await state.get_data()
    name = data.get("monitor_name", "")
    url = data.get("monitor_url", "")
    interval = data.get("monitor_interval", 300)
    if not name or not url:
        await message.answer("Ошибка: не хватает данных для монитора.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    await _process_monitor_add(message, name, url, interval)
    await state.clear()


async def _process_monitor_add(message: Message, name: str, url: str, interval: int, expected_status: int = 200):
    status_text = "⏳ Проверяю..."
    status_msg = await message.answer(status_text)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status = resp.status
                if status == expected_status:
                    status_text = f"✅ HTTP {status} — сайт доступен"
                else:
                    status_text = f"⚠️ HTTP {status} (ожидался {expected_status})"
    except Exception as e:
        status_text = f"⚠️ Ошибка: {str(e)[:100]}\nМонитор добавлен, но URL может быть недоступен."

    mid = db.add_monitor(
        user_id=message.from_user.id,
        name=name,
        url=url,
        interval=interval,
        expected_status=expected_status,
    )
    await status_msg.edit_text(
        f"🔍 Монитор #{mid} добавлен\n"
        f"Имя: {name}\n"
        f"URL: {url}\n"
        f"Проверка: {status_text}\n"
        f"Интервал: {_format_interval(interval)}"
    )



@router.message(lambda m: m.text and m.text == "/monitors")
@router.message(F.text == "🔍 Мониторы")
async def cmd_monitors(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    monitors = db.get_monitors(message.from_user.id)
    if not monitors:
        await message.answer(
            "Нет активных мониторов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить монитор", callback_data="add_monitor")]]
            ),
        )
        await message.answer("Выберите действие:")
        return

    text = "🔍 Активные мониторы:\n\n"
    buttons = []
    for idx, m in enumerate(monitors, 1):
        ls = m.get('last_status')
        expected = m.get('expected_status', 200)
        if ls is None or ls == '':
            status = "⏳ не проверялся"
        elif ls == 0:
            status = "❌ недоступен"
        elif ls == expected:
            status = f"✅ HTTP {ls}"
        else:
            status = f"⚠️ HTTP {ls} (ожидался {expected})"
        interval_str = _format_interval(m.get('check_interval', 300))
        text += f"#{idx} | {m['name']}\n"
        text += f"   {status} | {interval_str} | {m['url']}\n\n"
        buttons.append([InlineKeyboardButton(text=f"🗑 Удалить #{idx}", callback_data=f"del_monitor:{m['id']}")])

    buttons.append([InlineKeyboardButton(text="➕ Добавить монитор", callback_data="add_monitor")])
    await message.answer(text.strip(), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await message.answer("Выберите действие:")

@router.message(lambda m: m.text and m.text.startswith("/monitor_remove"))
async def cmd_monitor_remove(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "🗑 Введите ID монитора для удаления:\n"
            "Пример: 2",
        )
        await state.set_state(BotStates.waiting_monitor_remove)
        return

    try:
        mid = int(parts[1])
        user_monitors = db.get_monitors(message.from_user.id)
        if not any(m['id'] == mid for m in user_monitors):
            await message.answer("Нет доступа к этому монитору.")
            return
        db.remove_monitor(mid)
        await message.answer(f"Монитор #{mid} удалён.")
    except ValueError:
        await message.answer("Укажите числовой ID.")


@router.message(BotStates.waiting_monitor_remove)
async def process_monitor_remove(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    try:
        mid = int(message.text.strip())
        user_monitors = db.get_monitors(message.from_user.id)
        if not any(m['id'] == mid for m in user_monitors):
            await message.answer("Нет доступа к этому монитору.", reply_markup=cancel_keyboard)
            await state.clear()
            return
        db.remove_monitor(mid)
        await message.answer(f"Монитор #{mid} удалён.", reply_markup=cancel_keyboard)
    except ValueError:
        await message.answer("Укажите числовой ID.", reply_markup=cancel_keyboard)
    await state.clear()

@router.message(lambda m: m.text and m.text.startswith("/report"))
@router.message(F.text == "📊 Отчёт")
async def cmd_report(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    now = datetime.now(timezone.utc)
    text = f"📊 Ежедневный отчёт ({now.strftime('%Y-%m-%d %H:%M')})\n\n"

    reminders = db.get_user_reminders(message.from_user.id)
    text += f"⏰ Напоминаний: {len(reminders)}\n"

    monitors = db.get_monitors(message.from_user.id)
    text += f"🔍 Мониторов: {len(monitors)}\n"

    notes = db.get_notes(message.from_user.id)
    if notes:
        text += f"\n📝 Заметки:\n{notes}"

    memories = db.get_memories(message.from_user.id)
    if memories:
        text += f"\n🧠 Память: {len(memories)} фактов"

    await message.answer(text)


@router.message(lambda m: m.text and m.text.startswith("/memory_add"))
async def cmd_memory_add(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(
            "🧠 Что запомнить?\n"
            "Например: я люблю краткие ответы",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_memory_add)
        return

    if len(parts) == 2:
        category = "fact"
        content = parts[1]
    else:
        category = parts[1].lower()
        content = parts[2]
        if category not in ("fact", "preference", "task", "decision"):
            category = "fact"

    mid = db.add_memory(message.from_user.id, category, content)
    await message.answer(f"✅ Факт #{mid} сохранён: [{category}] {content}")


@router.message(BotStates.waiting_memory_add)
async def process_memory_add(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    content = (message.text or "").strip()
    if not content:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        return
    await state.update_data(memory_content=content)
    cat_names = {"fact": "📌 Факт", "preference": "❤️ Предпочтение", "task": "📋 Задача", "decision": "⚖️ Решение"}
    await message.answer(
        f"🧠 Запомнить: {content}\n\nВыбери категорию:",
        reply_markup=memory_category_keyboard(),
    )


@router.message(BotStates.waiting_task_text)
async def process_task_text(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await state.update_data(task_content=message.text.strip(), task_action="execute")
    await state.set_state(BotStates.waiting_task_time)
    await message.answer(
        "📋 Задача будет выполнена через AI при срабатывании.\n\nКогда выполнить?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏰ Через 5 минут", callback_data="task_time:5m")],
                [InlineKeyboardButton(text="⏰ Через час", callback_data="task_time:1h")],
                [InlineKeyboardButton(text="📅 Завтра 9:00", callback_data="task_time:tomorrow9")],
                [InlineKeyboardButton(text="🔁 Каждый день 7:00", callback_data="task_time:daily7")],
                [InlineKeyboardButton(text="🔁 Будние дни 9:00", callback_data="task_time:weekday9")],
                [InlineKeyboardButton(text="🔁 Пятница 18:00", callback_data="task_time:friday18")],
                [InlineKeyboardButton(text="✏️ Другое время", callback_data="task_time:manual")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
            ]
        ),
    )
    await message.answer("Выберите время:", reply_markup=cancel_keyboard)


@router.message(BotStates.waiting_task_time)
async def process_task_time_manual(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    data = await state.get_data()
    content = data.get("task_content", "")
    time_str = message.text.strip()
    trigger_at, recurring = parse_reminder(time_str)
    rid = db.add_reminder(
        user_id=message.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="execute",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await message.answer(
        f"⏰ Задача #{rid} установлена на {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
        f"Режим: 🤖 AI-выполнение\n"
        f"Текст: {content}",
    )
    await state.clear()


@router.callback_query(F.data.startswith("task_time:"))
async def cb_select_task_time(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    mode = callback.data.split(":", 1)[1]
    data = await state.get_data()
    content = data.get("task_content", "")
    now = datetime.now(timezone.utc)
    trigger_at = now
    recurring = None

    if mode == "5m":
        trigger_at = now + timedelta(minutes=5)
    elif mode == "1h":
        trigger_at = now + timedelta(hours=1)
    elif mode == "tomorrow9":
        trigger_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif mode == "daily7":
        trigger_at = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if trigger_at <= now:
            trigger_at += timedelta(days=1)
        recurring = "daily"
    elif mode == "weekday9":
        trigger_at = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if trigger_at <= now or trigger_at.weekday() >= 5:
            trigger_at += timedelta(days=1)
            while trigger_at.weekday() >= 5:
                trigger_at += timedelta(days=1)
        recurring = "weekday"
    elif mode == "friday18":
        trigger_at = now.replace(hour=18, minute=0, second=0, microsecond=0)
        days_ahead = (4 - now.weekday()) % 7
        if days_ahead == 0 and trigger_at <= now:
            days_ahead = 7
        trigger_at = now + timedelta(days=days_ahead)
        trigger_at = trigger_at.replace(hour=18, minute=0, second=0, microsecond=0)
        recurring = "friday"
    elif mode == "manual":
        await state.set_state(BotStates.waiting_task_time)
        await callback.message.answer(
            "⏰ Введите время задачи:\n"
            "Примеры:\n"
            "  через 5 минут\n"
            "  завтра в 9:00\n"
            "  каждый будний день в 7:00\n"
            "  понедельник в 10:00\n"
            "  еженедельно в пятницу 18:00",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Введите время вручную")
        return
    else:
        trigger_at = now + timedelta(minutes=5)

    rid = db.add_reminder(
        user_id=callback.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="execute",
    )
    from bot.bot import bot as aiogram_bot
    rec_label = f" ({recurring})" if recurring else ""
    await aiogram_bot.send_message(
        chat_id=callback.from_user.id,
        text=f"⏰ Задача #{rid} установлена на {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
             f"Режим: 🤖 AI-выполнение\n"
             f"Текст: {content}",
    )
    await state.clear()
    await callback.answer("Задача создана")


@router.message(lambda m: m.text and m.text == "/memory")
@router.message(F.text == "🧠 Память")
async def cmd_memory(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    memories = db.get_memories(message.from_user.id)
    if not memories:
        await message.answer(
            "Нет сохранённых фактов.\n"
            "Используй /memory_add <категория> <текст>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить факт", callback_data="add_memory")]]
            ),
        )
        await message.answer("Выберите действие:")
        return

    text = "🧠 Память:\n\n"
    buttons = []
    for idx, m in enumerate(memories, 1):
        cat = m.get('category', 'fact')
        content = m.get('content', '')
        text += f"#{idx} | [{cat}] {content}\n\n"
        buttons.append([InlineKeyboardButton(text=f"🗑 Удалить #{idx}", callback_data=f"del_memory:{m['id']}")])

    buttons.append([InlineKeyboardButton(text="➕ Добавить факт", callback_data="add_memory")])
    await message.answer(text.strip(), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await message.answer("Выберите действие:")


@router.message(lambda m: m.text and m.text.startswith("/memory_remove"))
async def cmd_memory_remove(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "🗑 Введите ID факта для удаления:\n"
            "Пример: 5",
        )
        await state.set_state(BotStates.waiting_memory_remove)
        return

    try:
        mid = int(parts[1])
        user_memories = db.get_memories(message.from_user.id)
        if not any(m['id'] == mid for m in user_memories):
            await message.answer("Нет доступа к этому факту.")
            return
        db.remove_memory(mid)
        await message.answer(f"Факт #{mid} удалён.")
    except ValueError:
        await message.answer("Укажите числовой ID.")


@router.message(BotStates.waiting_memory_remove)
async def process_memory_remove(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    try:
        mid = int(message.text.strip())
        user_memories = db.get_memories(message.from_user.id)
        if not any(m['id'] == mid for m in user_memories):
            await message.answer("Нет доступа к этому факту.", reply_markup=cancel_keyboard)
            await state.clear()
            return
        db.remove_memory(mid)
        await message.answer(f"Факт #{mid} удалён.", reply_markup=cancel_keyboard)
    except ValueError:
        await message.answer("Укажите числовой ID.", reply_markup=cancel_keyboard)
    await state.clear()


@router.message(lambda m: m.text and m.text.startswith("/remind_remove"))
async def cmd_remind_remove(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "🗑 Введите ID напоминания для удаления:\n"
            "Пример: 3",
        )
        await state.set_state(BotStates.waiting_remind_remove)
        return

    try:
        rid = int(parts[1])
        user_reminders = db.get_user_reminders(message.from_user.id)
        if not any(r['id'] == rid for r in user_reminders):
            await message.answer("Нет доступа к этому напоминанию.")
            return
        db.disable_reminder(rid)
        await message.answer(f"Напоминание #{rid} удалено.")
    except ValueError:
        await message.answer("Укажите числовой ID.")


@router.message(BotStates.waiting_remind_remove)
async def process_remind_remove(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    try:
        rid = int(message.text.strip())
        user_reminders = db.get_user_reminders(message.from_user.id)
        if not any(r['id'] == rid for r in user_reminders):
            await message.answer("Нет доступа к этому напоминанию.", reply_markup=cancel_keyboard)
            await state.clear()
            return
        db.disable_reminder(rid)
        await message.answer(f"Напоминание #{rid} удалено.", reply_markup=cancel_keyboard)
    except ValueError:
        await message.answer("Укажите числовой ID.", reply_markup=cancel_keyboard)
    await state.clear()


def _weather_emoji(desc: str) -> str:
    """Map weather description to an emoji."""
    d = desc.lower()
    if "thunder" in d or "storm" in d:
        return "⛈️"
    if "snow" in d or "sleet" in d or "blizzard" in d or "ice" in d:
        return "❄️"
    if "rain" in d or "drizzle" in d or "shower" in d:
        return "🌧️"
    if "clear" in d or "sunny" in d:
        return "☀️"
    if "partly" in d:
        return "⛅"
    if "cloud" in d or "overcast" in d:
        return "☁️"
    if "fog" in d or "mist" in d or "haze" in d:
        return "🌫️"
    if "wind" in d or "breeze" in d:
        return "💨"
    return "🌡️"


async def _get_wttr(city: str):
    async with aiohttp.ClientSession() as session:
        url = f"https://wttr.in/{city}?format=j1"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            text = await resp.text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return None, f"Invalid JSON from wttr.in: {text[:200]}"
            current = data.get("current_condition", [{}])[0]
            area = data.get("nearest_area", [{}])[0]
            area_name = area.get("areaName", [{}])[0].get("value", city)
            country = area.get("country", [{}])[0].get("value", "")
            desc = current.get("weatherDesc", [{}])[0].get("value", "")
            emoji = _weather_emoji(desc)
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", "?")
            wind = current.get("windspeedKmph", "?")
            wind_dir = current.get("winddir16Point", "")
            humidity = current.get("humidity", "?")
            pressure = current.get("pressure", "?")
            visibility = current.get("visibility", "?")
            text = (
                f"{emoji} Погода в {area_name}" + (f", {country}\n" if country else "\n")
                + (f"{emoji} {desc}\n" if desc else "")
                + f"🌡 Температура: {temp}°C (ощущается {feels}°C)\n"
                f"💨 Ветер: {wind} km/h {wind_dir}\n"
                f"💧 Влажность: {humidity}%\n"
                f"📊 Давление: {pressure} мм рт. ст.\n"
                f"👁 Видимость: {visibility} км\n\n"
                f"Источник: wttr.in"
            )
            return text, None


async def _get_open_meteo(city: str):
    """Fallback weather via Open-Meteo geocoding + weather API."""
    async with aiohttp.ClientSession() as session:
        # Geocode
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=ru"
        async with session.get(geo_url, timeout=aiohttp.ClientTimeout(total=10)) as geo_resp:
            if geo_resp.status != 200:
                return None, f"Geocoding HTTP {geo_resp.status}"
            geo = await geo_resp.json()
            results = geo.get("results", [])
            if not results:
                return None, "Город не найден"
            loc = results[0]
            lat = loc["latitude"]
            lon = loc["longitude"]
            name = loc.get("name", city)
            country = loc.get("country", "")

        # Weather
        w_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,"
            f"apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,pressure_msl"
        )
        async with session.get(w_url, timeout=aiohttp.ClientTimeout(total=10)) as w_resp:
            if w_resp.status != 200:
                return None, f"Weather HTTP {w_resp.status}"
            w = await w_resp.json()
            cur = w.get("current", {})
            temp = cur.get("temperature_2m", "?")
            feels = cur.get("apparent_temperature", "?")
            humidity = cur.get("relative_humidity_2m", "?")
            wind = cur.get("wind_speed_10m", "?")
            wind_dir = cur.get("wind_direction_10m", "")
            pressure = cur.get("pressure_msl", "?")
            code = cur.get("weather_code", 0)
            # WMO weather code mapping
            wmo_desc = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Fog", 48: "Depositing rime fog",
                51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
                71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
                80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
                95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
            }
            desc = wmo_desc.get(code, "Unknown")
            emoji = _weather_emoji(desc)
            text = (
                f"{emoji} Погода в {name}" + (f", {country}\n" if country else "\n")
                + (f"{emoji} {desc}\n" if desc else "")
                + f"🌡 Температура: {temp}°C (ощущается {feels}°C)\n"
                f"💨 Ветер: {wind} km/h {wind_dir}\n"
                f"💧 Влажность: {humidity}%\n"
                f"📊 Давление: {pressure} гПа\n\n"
                f"Источник: Open-Meteo"
            )
            return text, None


async def get_weather(city: str):
    """Fetch weather with fallback: wttr.in → Open-Meteo."""
    try:
        return await _get_wttr(city)
    except Exception as e:
        print(f"[WEATHER] wttr.in failed: {e}, trying fallback")
    try:
        return await _get_open_meteo(city)
    except Exception as e:
        return None, str(e)[:200]


@router.message(lambda m: m.text and m.text.startswith("/weather"))
async def cmd_weather(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🌤 Введите название города:\n"
            "Пример: Moscow",
        )
        await state.set_state(BotStates.waiting_weather)
        return

    await _process_weather(message, parts[1].strip())


@router.message(F.text == "🌤 Погода")
async def btn_weather(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    await message.answer(
        "🌤 Введите название города:\n"
        "Пример: Moscow",
    )
    await state.set_state(BotStates.waiting_weather)


async def _process_weather(message: Message, city: str):
    await message.answer(f"🌤 Ищу погоду: {city}...")
    text, error = await get_weather(city)
    if error:
        await message.answer(f"❌ Ошибка погоды: {error}")
        return
    await message.answer(text)


@router.message(BotStates.waiting_weather)
async def process_weather(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await _process_weather(message, message.text.strip())
    await state.clear()


@router.message(lambda m: m.text and m.text == "/news")
@router.message(F.text == "📰 Новости")
async def cmd_news(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    await message.answer("📰 Ищу актуальные новости...")

    result, error = await ollama_web_search("последние новости сегодня", max_results=5)
    if error:
        await message.answer(f"❌ {error}")
        return

    items = result.get("results", [])
    if not items:
        await message.answer("Новостей не найдено.")
        return

    text = "📰 Актуальные новости:\n\n"
    for i, item in enumerate(items[:5], 1):
        title = item.get("title", "Без названия")
        url = item.get("url", "")
        # Extract domain for source attribution
        source = ""
        if url:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace("www.", "")
                source = f" ({domain})"
            except:
                pass
        # Short snippet: strip newlines, truncate cleanly
        snippet = _extract_main_text(item.get("content", ""), max_len=200)
        text += f"{i}. {title}{source}\n"
        if snippet:
            text += f"   {snippet}\n"
        if url:
            text += f"   {url}\n"
        text += "\n"

    await message.answer(text[:4096])


@router.message(lambda m: m.text and m.text.startswith("/search"))
async def cmd_search(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🔍 Введите поисковый запрос:\n"
            "Пример: последние новости о Tesla",
        )
        await state.set_state(BotStates.waiting_search)
        return

    await _process_search(message, parts[1].strip())


@router.message(F.text == "🔍 Поиск")
async def btn_search(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    await message.answer(
        "🔍 Введите поисковый запрос:\n"
        "Пример: последние новости о Tesla",
    )
    await state.set_state(BotStates.waiting_search)


async def _process_search(message: Message, query: str):
    await message.answer(f"🔍 Ищу в интернете: {query}...")

    result, error = await ollama_web_search(query, max_results=5)
    if error:
        await message.answer(f"❌ Ошибка поиска: {error}")
        return

    if not result or "results" not in result:
        await message.answer("Ничего не найдено.")
        return

    items = result["results"]
    if not items:
        await message.answer("Ничего не найдено.")
        return

    text = f"🔍 {query}\n\n"
    for i, item in enumerate(items[:5], 1):
        title = item.get("title", "Без названия")
        url = item.get("url", "")
        snippet = _extract_main_text(item.get("content", ""), max_len=200)

        # Extract domain for source tag
        source = ""
        if url:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace("www.", "")
                if domain:
                    source = f" ({domain})"
            except Exception:
                pass

        text += f"{i}. {title}{source}\n"
        if snippet:
            text += f"   {snippet}\n"
        if url:
            text += f"   {url}\n"
        text += "\n"

    await message.answer(text[:4096])


@router.message(BotStates.waiting_search)
async def process_search(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await _process_search(message, message.text.strip())
    await state.clear()


@router.message(lambda m: m.text and m.text.startswith("/fetch"))
async def cmd_fetch(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📄 Введите URL для загрузки:\n"
            "Пример: https://example.com/article",
        )
        await state.set_state(BotStates.waiting_fetch)
        return

    await _process_fetch(message, parts[1].strip())


async def _process_fetch(message: Message, url: str):
    await message.answer(f"📄 Загружаю: {url}...")

    result, error = await ollama_web_fetch(url)
    if error:
        await message.answer(f"❌ Ошибка загрузки: {error}")
        return

    title = result.get("title", "Без названия")
    content = result.get("content", "")[:3000]
    links = result.get("links", [])[:10]

    text = f"📄 {title}\n\n{content}\n"
    if links:
        text += "\n🔗 Ссылки на странице:\n"
        for link in links:
            text += f"- {link}\n"

    # Telegram limit
    if len(text) > 4096:
        text = text[:4090] + "..."

    await message.answer(text)


@router.message(BotStates.waiting_fetch)
async def process_fetch(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await _process_fetch(message, message.text.strip())
    await state.clear()


# --- Inline delete callbacks ---

@router.callback_query(F.data.startswith("del_reminder:"))
async def cb_del_reminder(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        rid = int(callback.data.split(":", 1)[1])
        # Verify ownership
        user_reminders = db.get_user_reminders(callback.from_user.id)
        if not any(r['id'] == rid for r in user_reminders):
            await callback.answer("Нет доступа", show_alert=True)
            return
        db.disable_reminder(rid)
        await callback.answer(f"Напоминание #{rid} удалено")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.edit_text(f"✅ Напоминание #{rid} удалено.")
        await callback.message.answer("Напоминание удалено.")
    except Exception as e:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("del_monitor:"))
async def cb_del_monitor(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        mid = int(callback.data.split(":", 1)[1])
        # Verify ownership
        user_monitors = db.get_monitors(callback.from_user.id)
        if not any(m['id'] == mid for m in user_monitors):
            await callback.answer("Нет доступа", show_alert=True)
            return
        db.remove_monitor(mid)
        await callback.answer(f"Монитор #{mid} удалён")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.edit_text(f"✅ Монитор #{mid} удалён.")
        await callback.message.answer("Монитор удалён.")
    except Exception as e:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("del_memory:"))
async def cb_del_memory(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        mid = int(callback.data.split(":", 1)[1])
        # Verify ownership
        user_memories = db.get_memories(callback.from_user.id)
        if not any(m['id'] == mid for m in user_memories):
            await callback.answer("Нет доступа", show_alert=True)
            return
        db.remove_memory(mid)
        await callback.answer(f"Факт #{mid} удалён")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.edit_text(f"✅ Факт #{mid} удалён.")
        await callback.message.answer("Факт удалён.")
    except Exception as e:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("mem_cat:"))
async def cb_select_memory_category(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    category = callback.data.split(":", 1)[1]
    cat_names = {"fact": "📌 Факт", "preference": "❤️ Предпочтение", "task": "📋 Задача", "decision": "⚖️ Решение"}
    await callback.answer(f"Выбрано: {cat_names.get(category, category)}")

    data = await state.get_data()
    content = data.get("memory_content", "")

    if content:
        mid = db.add_memory(callback.from_user.id, category, content)
        await callback.message.answer(
            f"✅ Факт #{mid} сохранён: [{category}] {content}",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.clear()
        return

    if category == "task":
        await state.set_state(BotStates.waiting_task_text)
        await callback.message.answer(
            "📋 Новая задача\n\nВведите текст задачи:\nПример: проверить отчёт по акциям",
            reply_markup=cancel_keyboard,
        )
        return

    await state.update_data(memory_category=category)
    await state.set_state(BotStates.waiting_memory_add)
    await callback.message.answer(
        f"{cat_names.get(category, category)}\n\nВведите текст:",
        reply_markup=cancel_keyboard,
    )


@router.callback_query(F.data == "add_memory")
async def cb_add_memory(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Добавление факта")
    await callback.message.answer(
        "🧠 Что запомнить?\n"
        "Например: я люблю краткие ответы",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_memory_add)


@router.callback_query(F.data == "add_reminder")
async def cb_add_reminder(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Добавление напоминания")
    await callback.message.answer(
        "⏰ Чего напомнить?\n"
        "Например: позвонить брокеру",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_remind)


@router.callback_query(F.data == "add_monitor")
async def cb_add_monitor(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Добавление монитора")
    await callback.message.answer(
        "🔍 Название монитора?\n"
        "Например: Google",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_monitor_name)


# Register button handlers for instant FSM routing
_BUTTON_HANDLERS.update({
    "🔍 Поиск": btn_search,
    "⏰ Напоминание": btn_remind,
    "🧠 Память": cmd_memory,
})
@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    await callback.answer()

