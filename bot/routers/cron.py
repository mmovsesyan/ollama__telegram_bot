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
    memory_menu_keyboard,
    recurring_suggest_keyboard,
    reminder_quick_keyboard,
    task_quick_keyboard,
    note_quick_keyboard,
    monitor_interval_keyboard,
)
from bot.settings import ALLOWED_CHAT_IDS, OLLAMA_MODEL, SYSTEM_MESSAGE
from bot.ollama import OllamaChat, OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.tasks_exec import execute_smart

router = Router()

db = None  # injected in __init__

# Known command buttons that should cancel pending FSM input
_COMMAND_BUTTONS = {
    "💬 Чат", "🔍 Поиск", "⏰ Напомнить", "📋 Задача",
    "📝 Заметка", "🧠 Память", "🌤 Погода", "📊 Отчёт",
    "❓ Помощь", "🗑 Очистить",
}

# Button text → handler mapping for instant routing when pressed during FSM
_BUTTON_HANDLERS: dict[str, callable] = {}


async def _fsm_guard(message: Message, state: FSMContext) -> bool:
    """If user sends a cancel/command while in FSM state, cancel state and return True."""
    text = message.text or ""

    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=command_keyboard)
        return True

    if text in _COMMAND_BUTTONS:
        await state.clear()
        handler = _BUTTON_HANDLERS.get(text)
        if handler:
            await handler(message, state)
        else:
            await message.answer(
                "Текущее действие отменено. Нажми кнопку ещё раз.",
                reply_markup=command_keyboard,
            )
        return True

    if text.startswith("/"):
        await state.clear()
        await message.answer(
            "Текущее действие отменено. Введи команду повторно.",
            reply_markup=command_keyboard,
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


import html


def _clean_snippet(text: str, max_len: int = 200) -> str:
    """Aggressively clean a web-search content snippet for Telegram display."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    garbage = [
        r"В приложении удобнее", r"RuStore", r"Samsung Galaxy Store", r"Huawei AppGallery",
        r"Xiaomi GetApps", r"AppGallery", r"GetApps", r"КУПИТЬ", r"ДОСТАВКА", r"СПОСОБЫ",
        r"отслеживать", r"Сравнить", r"В список желаний", r"Сделать любимым", r"Оставить отзыв",
        r"Подробнее", r"ПОДРОБНЕЕ", r"рейтинг:", r"\(1\)", r"ISBN", r"Артикул", r"Артикул:",
        r"товара:", r"Попробуйте обновленную версию", r"LiveLib", r"Часть функций", r"бета-версии",
        r"Моя оценка", r"Все уведомления", r"Рецензии", r"Цитаты", r"Издания и произведения",
        r"Пожаловаться", r"прочитали", r"планируют", r"рецензий", r"цитаты", r"№\d+ в ",
        r"Goodreads", r"Вподобайки", r"Характеристики", r"Переглянути фото", r"Паперова",
        r"Електронна", r"В наявності", r"Відправка:", r"Не получается оформить заказ?",
        r"укажите код", r"СПОСОБЫ ОПЛАТЫ", r"код \d+", r"КУПИТЬ С ДОСТАВКОЙ", r"книгу в наявності",
    ]
    for g in garbage:
        text = re.sub(g, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences:
        snippet = sentences[0]
        if len(snippet) < 60 and len(sentences) > 1:
            snippet += " " + sentences[1]
    else:
        snippet = text
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rsplit(" ", 1)[0] + "..."
    return snippet.strip()


def _extract_main_text(html_text: str, max_len: int = 250) -> str:
    """Use BeautifulSoup to strip nav/scripts and extract the longest coherent paragraph."""
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return _clean_snippet(html_text, max_len)

    soup = BeautifulSoup(html_text, "lxml")
    for tag_name in ("script", "style", "nav", "header", "footer", "aside", "form", "button", "noscript"):
        for t in soup.find_all(tag_name):
            t.decompose()

    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
        if 30 < len(desc) < 300:
            return desc[:max_len].rsplit(" ", 1)[0] + "..." if len(desc) > max_len else desc

    candidates = []
    for tag in soup.find_all(("p", "div", "article", "section", "span")):
        txt = tag.get_text(separator=" ", strip=True)
        if len(txt) < 30:
            continue
        noise = txt.count("|") + txt.count("→") + txt.count("↳") + txt.count("▸") + txt.count("·")
        score = len(txt) - noise * 10
        candidates.append((score, txt))
    if not candidates:
        return _clean_snippet(html_text, max_len)
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
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
    now = datetime.now(timezone.utc)
    text = text.lower().strip()
    recurrence = None

    def _extract_time(txt: str) -> tuple[int, int]:
        m = re.search(r'(\d{1,2}):(\d{2})', txt)
        if m:
            h = max(0, min(23, int(m.group(1))))
            minute = max(0, min(59, int(m.group(2))))
            return h, minute
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

    if re.search(r'ежедневно|каждый\s+день|every\s+day|daily', text):
        recurrence = "daily"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, recurrence

    if re.search(r'каждый\s+будний|будние|каждый\s+рабочий|weekday|по\s+будням', text):
        recurrence = "weekday"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now or target.weekday() >= 5:
            target += timedelta(days=1)
            while target.weekday() >= 5:
                target += timedelta(days=1)
        return target, recurrence

    if re.search(r'каждый\s+выходной|выходные|weekend', text):
        recurrence = "weekend"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now or target.weekday() < 5:
            target += timedelta(days=1)
            while target.weekday() < 5:
                target += timedelta(days=1)
        return target, recurrence

    if re.search(r'еженедельно|every\s+week|weekly|каждую\s+неделю', text):
        recurrence = "weekly"
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(weeks=1)
        return target, recurrence

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

    through_match = re.search(r'через\s+(\d+)\s*(минут|мин|час|ч|день|дня|дней|д)?', text)
    if through_match:
        num = int(through_match.group(1))
        unit = (through_match.group(2) or "").lower()
        if unit in ("минут", "мин", "м"):
            return now + timedelta(minutes=num), None
        if unit in ("час", "ч"):
            return now + timedelta(hours=num), None
        if unit in ("день", "дня", "дней", "д"):
            return now + timedelta(days=num), None
        return now + timedelta(minutes=num), None

    today_match = re.search(r'сегодня\s+в\s+(\d{1,2}):(\d{2})', text)
    if today_match:
        h = max(0, min(23, int(today_match.group(1))))
        m = max(0, min(59, int(today_match.group(2))))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, None

    if "завтра" in text:
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            h = max(0, min(23, int(time_match.group(1))))
            m = max(0, min(59, int(time_match.group(2))))
        else:
            h, m = 9, 0
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=h, minute=m, second=0, microsecond=0), None

    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, None
    except Exception:
        pass

    return now + timedelta(minutes=5), None


async def _classify_memory(content: str) -> str:
    """Use Ollama to pick the best memory category for content."""
    prompt = (
        "Ты классифицируешь заметки пользователя. Выбери одну категорию:\n"
        "- fact: факт о пользователе, проекте или мире\n"
        "- preference: предпочтение, вкус, правило поведения\n"
        "- note: обычная заметка, напоминание, мысль\n\n"
        "Ответь ТОЛЬКО одним словом: fact, preference или note.\n\n"
        f"Текст: {content}\n\n"
        "Категория:"
    )
    messages = [
        OllamaChatMessage(role="system", content=SYSTEM_MESSAGE),
        OllamaChatMessage(role="user", content=prompt),
    ]
    result = ""
    try:
        async for is_done, chunk in generate_chat_completion(messages, OLLAMA_MODEL, temperature=0.2):
            if is_done:
                break
            if isinstance(chunk, OllamaErrorChunk):
                break
            result += chunk.message.content
    except Exception as e:
        print(f"[AUTO MEMORY] Classification failed: {e}")
    result = result.strip().lower()
    if result in ("fact", "preference", "note"):
        return result
    return "note"


# --- Reminders ---

@router.message(lambda m: m.text and (m.text == "/remind" or m.text.startswith("/remind ")))
async def cmd_remind(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
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


@router.message(F.text == "⏰ Напомнить")
async def btn_remind(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    await message.answer(
        "⏰ Чего напомнить?\n"
        "Например: позвонить брокеру",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_remind)


async def _process_remind(user_id: int, text: str, action: str = "notify"):
    if db is None:
        from bot.bot import bot as aiogram_bot
        await aiogram_bot.send_message(chat_id=user_id, text="База данных недоступна.", reply_markup=command_keyboard)
        return

    trigger_at, recurring = parse_reminder(text)

    time_patterns = [
        r"^(через \d+ (?:минут|час|день|дней|дня))",
        r"^(завтра в \d{1,2}:\d{2})",
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
        r"^(\d{2}:\d{2})",
    ]

    content = text
    for pattern in time_patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
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

    time_patterns = [
        r"^(через \d+ (?:минут|час|день|дней|дня))",
        r"^(завтра в \d{1,2}:\d{2})",
        r"^(сегодня в \d{1,2}:\d{2})",
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
        r"^(\d{1,2}:\d{2})",
    ]

    content = text
    for pattern in time_patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            time_str = match.group(1)
            content = text[len(time_str):].strip()
            break

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
        await message.answer("Введи текст напоминания.", reply_markup=cancel_keyboard)
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
        await callback.answer("Введи время")
        return
    else:
        trigger_at = now + timedelta(minutes=5)

    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        await state.clear()
        return

    rid = db.add_reminder(
        user_id=callback.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="notify",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await callback.message.answer(
        f"✅ Напоминание #{rid} добавлено\n"
        f"🕐 Сработает: {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
        f"📝 Текст: {content}",
        reply_markup=command_keyboard,
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
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    rid = db.add_reminder(
        user_id=message.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="notify",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await message.answer(
        f"✅ Напоминание #{rid} добавлено\n"
        f"🕐 Сработает: {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
        f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.message(lambda m: m.text and m.text == "/reminders")
async def cmd_reminders(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    reminders = db.get_user_reminders(message.from_user.id)
    if not reminders:
        await message.answer(
            "Нет активных напоминаний.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить напоминание", callback_data="add_reminder")]]
            ),
        )
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
    await message.answer("Главное меню:", reply_markup=command_keyboard)


@router.message(lambda m: m.text and m.text.startswith("/remind_cancel"))
async def cmd_remind_cancel(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "❌ Введи ID напоминания для отмены:\n"
            "Пример: 3",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_remind_cancel)
        return

    try:
        rid = int(parts[1])
        user_reminders = db.get_user_reminders(message.from_user.id)
        if not any(r['id'] == rid for r in user_reminders):
            await message.answer("Нет доступа к этому напоминанию.", reply_markup=command_keyboard)
            return
        db.disable_reminder(rid)
        await message.answer(f"✅ Напоминание #{rid} удалено.", reply_markup=command_keyboard)
    except ValueError:
        await message.answer("Укажи числовой ID напоминания.", reply_markup=command_keyboard)


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
        await message.answer(f"✅ Напоминание #{rid} удалено.", reply_markup=command_keyboard)
    except ValueError:
        await message.answer("Укажи числовой ID напоминания.", reply_markup=cancel_keyboard)
    await state.clear()


# --- Tasks (AI-executed scheduled jobs) ---

@router.message(F.text == "📋 Задача")
async def btn_task(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    await message.answer(
        "📋 Какую задачу выполнить?\n"
        "Я сам выполню её в указанное время.\n\n"
        "Примеры:\n"
        "• пришли погоду в Москве\n"
        "• поищи последние новости Tesla\n"
        "• составь краткий отчёт",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_task_text)


@router.message(lambda m: m.text and m.text == "/task")
async def cmd_task(message: Message, state: FSMContext):
    await state.clear()
    await btn_task(message, state)


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
        reply_markup=task_quick_keyboard(),
    )


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
        f"✅ Задача #{rid} добавлена\n"
        f"🕐 Сработает: {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
        f"🤖 Режим: AI-выполнение\n"
        f"📝 Текст: {content}",
        reply_markup=command_keyboard,
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
    if not content:
        await callback.answer("Ошибка: нет текста задачи", show_alert=True)
        await state.clear()
        return

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
        if target := trigger_at:
            if target <= now or target.weekday() >= 5:
                target += timedelta(days=1)
                while target.weekday() >= 5:
                    target += timedelta(days=1)
            trigger_at = target
        recurring = "weekday"
    elif mode == "friday18":
        days_ahead = (4 - now.weekday()) % 7
        if days_ahead == 0 and now.replace(hour=18, minute=0, second=0, microsecond=0) <= now:
            days_ahead = 7
        trigger_at = now + timedelta(days=days_ahead)
        trigger_at = trigger_at.replace(hour=18, minute=0, second=0, microsecond=0)
        recurring = "friday"
    elif mode == "manual":
        await state.set_state(BotStates.waiting_task_time)
        await callback.message.answer(
            "⏰ Введи время задачи:\n"
            "Примеры:\n"
            "  через 5 минут\n"
            "  завтра в 9:00\n"
            "  каждый будний день в 7:00\n"
            "  понедельник в 10:00\n"
            "  еженедельно в пятницу 18:00",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Введи время вручную")
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
    rec_label = f" ({recurring})" if recurring else ""
    from bot.bot import bot as aiogram_bot
    await aiogram_bot.send_message(
        chat_id=callback.from_user.id,
        text=f"✅ Задача #{rid} добавлена\n"
             f"🕐 Сработает: {trigger_at.strftime('%Y-%m-%d %H:%M')}{rec_label}\n"
             f"🤖 Режим: AI-выполнение\n"
             f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()
    await callback.answer("Задача создана")


# --- Notes ---

@router.message(F.text == "📝 Заметка")
async def btn_note(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return
    notes = db.get_notes(message.from_user.id)
    if notes:
        await message.answer(
            f"📝 Твои заметки:\n{notes}\n\nХочешь добавить ещё одну?",
            reply_markup=note_quick_keyboard(),
        )
    else:
        await message.answer(
            "📝 Что записать?\n"
            "Например: купить акции TSLA",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_note)


@router.message(lambda m: m.text and m.text.startswith("/note"))
async def cmd_note(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        notes = db.get_notes(message.from_user.id)
        if notes:
            await message.answer(f"📝 Твои заметки:\n{notes}", reply_markup=command_keyboard)
        else:
            await message.answer(
                "📝 Что записать?\n"
                "Пример: купить акции TSLA",
                reply_markup=cancel_keyboard,
            )
            await state.set_state(BotStates.waiting_note)
        return

    db.add_note(message.from_user.id, parts[1])
    await message.answer(
        f"✅ Заметка сохранена. AI будет помнить это.\n\n📝 {parts[1]}",
        reply_markup=command_keyboard,
    )


@router.callback_query(F.data == "note_quick:manual")
async def cb_note_manual(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.answer(
        "📝 Что записать?",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_note)
    await callback.answer("Введи заметку")


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
    await message.answer(
        f"✅ Заметка сохранена. AI будет помнить это.\n\n📝 {message.text}",
        reply_markup=command_keyboard,
    )
    await state.clear()


# --- Monitors ---

@router.message(lambda m: m.text and m.text.startswith("/monitor_add"))
async def cmd_monitor_add(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
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
        await message.answer("Введи название монитора.", reply_markup=cancel_keyboard)
        return
    await state.update_data(monitor_name=name)
    await state.set_state(BotStates.waiting_monitor_url)
    await message.answer(
        f"🔍 Монитор: {name}\n\nВведи URL:\n"
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
        await message.answer("Введи URL.", reply_markup=cancel_keyboard)
        return
    await state.update_data(monitor_url=url)
    await state.set_state(BotStates.waiting_monitor_interval)
    await message.answer(
        "🔍 Интервал проверки?\n"
        "Например: 5m, 1h, или 300 (секунд)",
        reply_markup=monitor_interval_keyboard(),
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
        await message.answer("Ошибка: не хватает данных для монитора.", reply_markup=command_keyboard)
        await state.clear()
        return
    await _process_monitor_add(message, name, url, interval)
    await state.clear()


async def _process_monitor_add(message: Message, name: str, url: str, interval: int, expected_status: int = 200):
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

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
        expected_status=expected_status,
        interval=interval,
    )
    await status_msg.edit_text(
        f"✅ Монитор #{mid} добавлен\n"
        f"📝 Имя: {name}\n"
        f"🔗 URL: {url}\n"
        f"📊 Проверка: {status_text}\n"
        f"🕐 Интервал: {_format_interval(interval)}"
    )
    await message.answer(
        "Монитор активен. Я пришлю уведомление, если сайт станет недоступен.",
        reply_markup=command_keyboard,
    )


@router.message(lambda m: m.text and m.text == "/monitors")
async def cmd_monitors(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    monitors = db.get_monitors(message.from_user.id)
    if not monitors:
        await message.answer(
            "Нет активных мониторов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить монитор", callback_data="add_monitor")]]
            ),
        )
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
    await message.answer("Главное меню:", reply_markup=command_keyboard)


@router.message(lambda m: m.text and m.text.startswith("/monitor_remove"))
async def cmd_monitor_remove(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "🗑 Введи ID монитора для удаления:\n"
            "Пример: 2",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_monitor_remove)
        return

    try:
        mid = int(parts[1])
        user_monitors = db.get_monitors(message.from_user.id)
        if not any(m['id'] == mid for m in user_monitors):
            await message.answer("Нет доступа к этому монитору.", reply_markup=command_keyboard)
            return
        db.remove_monitor(mid)
        await message.answer(f"✅ Монитор #{mid} удалён.", reply_markup=command_keyboard)
    except ValueError:
        await message.answer("Укажи числовой ID.", reply_markup=command_keyboard)


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
        await message.answer(f"✅ Монитор #{mid} удалён.", reply_markup=command_keyboard)
    except ValueError:
        await message.answer("Укажи числовой ID.", reply_markup=cancel_keyboard)
    await state.clear()


# --- Report ---

@router.message(lambda m: m.text and m.text.startswith("/report"))
@router.message(F.text == "📊 Отчёт")
async def cmd_report(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    now = datetime.now(timezone.utc)
    text = f"📊 Ежедневный отчёт ({now.strftime('%Y-%m-%d %H:%M')})\n\n"

    reminders = db.get_user_reminders(message.from_user.id)
    text += f"⏰ Напоминаний / задач: {len(reminders)}\n"

    monitors = db.get_monitors(message.from_user.id)
    text += f"🔍 Мониторов: {len(monitors)}\n"

    notes = db.get_notes(message.from_user.id)
    if notes:
        text += f"\n📝 Заметки:\n{notes}"

    memories = db.get_memories(message.from_user.id)
    if memories:
        text += f"\n🧠 Память: {len(memories)} фактов"

    await message.answer(text, reply_markup=command_keyboard)


# --- Memory ---

@router.message(lambda m: m.text and m.text == "/memory")
@router.message(F.text == "🧠 Память")
async def cmd_memory(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    await message.answer(
        "🧠 Память — что делаем?",
        reply_markup=memory_menu_keyboard(),
    )


@router.message(lambda m: m.text and m.text.startswith("/memory_add"))
async def cmd_memory_add(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(
            "🧠 Что запомнить?\n"
            "Например: я люблю краткие ответы",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_memory_add)
        await state.update_data(memory_category="fact")
        return

    if len(parts) == 2:
        category = "fact"
        content = parts[1]
    else:
        category = parts[1].lower()
        content = parts[2]
        if category not in ("fact", "preference", "note"):
            category = "fact"

    mid = db.add_memory(message.from_user.id, category, content)
    cat_names = {"fact": "📌 Факт", "preference": "❤️ Предпочтение", "note": "📝 Заметка"}
    await message.answer(
        f"✅ Сохранено: {cat_names.get(category, category)}\n"
        f"#{mid} | {content}",
        reply_markup=command_keyboard,
    )


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

    data = await state.get_data()
    category = data.get("memory_category", "auto")
    cat_names = {"fact": "📌 Факт", "preference": "❤️ Предпочтение", "note": "📝 Заметка"}

    # Memory is not for scheduled actions. Detect time-like requests and redirect.
    time_patterns = [
        r"кажд(ый|ое|ую)\s+",
        r"ежедневно|еженедельно|ежемесячно|по\s+будням|по\s+выходным|будни|выходные",
        r"через\s+\d+",
        r"завтра\s+в\s+\d{1,2}:\d{2}",
        r"сегодня\s+в\s+\d{1,2}:\d{2}",
        r"в\s+\d{1,2}:\d{2}",
        r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}",
        r"утра|дня|вечера|ночи",
        r"понедельник|вторник|среда|четверг|пятница|суббота|воскресенье",
    ]
    looks_scheduled = any(re.search(p, content, re.IGNORECASE) for p in time_patterns)
    if looks_scheduled:
        await message.answer(
            "🧠 Это похоже на задачу или напоминание, а не на факт/предпочтение/заметку.\n\n"
            "Используй кнопки:\n"
            "📋 Задача — если хочешь, чтобы AI сам выполнил по расписанию\n"
            "⏰ Напоминание — если нужно просто напомнить",
            reply_markup=command_keyboard,
        )
        await state.clear()
        return

    if category == "auto":
        await message.answer("🤖 Определяю категорию...")
        category = await _classify_memory(content)

    if category not in ("fact", "preference", "note"):
        category = "note"

    mid = db.add_memory(message.from_user.id, category, content)
    await message.answer(
        f"✅ Сохранено: {cat_names.get(category, category)}\n"
        f"#{mid} | {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.message(lambda m: m.text and m.text.startswith("/memory_remove"))
async def cmd_memory_remove(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "🗑 Введи ID факта для удаления:\n"
            "Пример: 5",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_memory_remove)
        return

    try:
        mid = int(parts[1])
        user_memories = db.get_memories(message.from_user.id)
        if not any(m['id'] == mid for m in user_memories):
            await message.answer("Нет доступа к этому факту.", reply_markup=command_keyboard)
            return
        db.remove_memory(mid)
        await message.answer(f"✅ Факт #{mid} удалён.", reply_markup=command_keyboard)
    except ValueError:
        await message.answer("Укажи числовой ID.", reply_markup=command_keyboard)


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
        await message.answer(f"✅ Факт #{mid} удалён.", reply_markup=command_keyboard)
    except ValueError:
        await message.answer("Укажи числовой ID.", reply_markup=cancel_keyboard)
    await state.clear()


@router.callback_query(F.data.startswith("memory_menu:"))
async def cb_memory_menu(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]

    if action == "show":
        await _show_memories(callback.from_user.id, callback.message)
        await callback.answer("Показываю память")
        return

    if action == "add_auto":
        await callback.message.answer(
            "🧠 Что запомнить? Я сам определю категорию.\n"
            "Например: я люблю краткие ответы",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_memory_add)
        await state.update_data(memory_category="auto")
        await callback.answer("Введи текст")
        return

    if action == "add_fact":
        await state.set_state(BotStates.waiting_memory_add)
        await state.update_data(memory_category="fact")
        await callback.message.answer(
            "📌 Какой факт сохранить?\n"
            "Например: я работаю над проектом X",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Добавляем факт")
        return

    if action == "add_preference":
        await state.set_state(BotStates.waiting_memory_add)
        await state.update_data(memory_category="preference")
        await callback.message.answer(
            "❤️ Какое предпочтение сохранить?\n"
            "Например: я люблю краткие ответы",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Добавляем предпочтение")
        return

    if action == "add_note":
        await state.set_state(BotStates.waiting_memory_add)
        await state.update_data(memory_category="note")
        await callback.message.answer(
            "📝 Какую заметку сохранить?\n"
            "Например: купить акции TSLA",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Добавляем заметку")
        return


async def _show_memories(user_id: int, message: Message):
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return
    memories = db.get_memories(user_id)
    if not memories:
        await message.answer(
            "Нет сохранённых записей.",
            reply_markup=memory_menu_keyboard(),
        )
        return

    cat_names = {"fact": "📌 Факт", "preference": "❤️ Предпочтение", "note": "📝 Заметка", "task": "📋 Задача", "decision": "⚖️ Решение"}
    text = "🧠 Память:\n\n"
    buttons = []
    for idx, m in enumerate(memories, 1):
        cat = m.get('category', 'fact')
        content = m.get('content', '')
        text += f"#{idx} | {cat_names.get(cat, cat)}\n{content}\n\n"
        buttons.append([InlineKeyboardButton(text=f"🗑 Удалить #{idx}", callback_data=f"del_memory:{m['id']}")])

    buttons.append([InlineKeyboardButton(text="➕ Добавить", callback_data="memory_menu:add_auto")])
    await message.answer(text.strip(), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await message.answer("Главное меню:", reply_markup=command_keyboard)


# --- Inline delete callbacks ---

@router.callback_query(F.data.startswith("del_reminder:"))
async def cb_del_reminder(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    try:
        rid = int(callback.data.split(":", 1)[1])
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
    except Exception as e:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("del_monitor:"))
async def cb_del_monitor(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    try:
        mid = int(callback.data.split(":", 1)[1])
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
    except Exception as e:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("del_memory:"))
async def cb_del_memory(callback: CallbackQuery):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return
    try:
        mid = int(callback.data.split(":", 1)[1])
        user_memories = db.get_memories(callback.from_user.id)
        if not any(m['id'] == mid for m in user_memories):
            await callback.answer("Нет доступа", show_alert=True)
            return
        db.remove_memory(mid)
        await callback.answer(f"Запись #{mid} удалена")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.edit_text(f"✅ Запись #{mid} удалена.")
    except Exception as e:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("mem_cat:"))
async def cb_select_memory_category(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return

    category = callback.data.split(":", 1)[1]
    cat_names = {"fact": "📌 Факт", "preference": "❤️ Предпочтение", "note": "📝 Заметка"}

    if category == "auto":
        await callback.answer("Анализирую текст...")
        data = await state.get_data()
        content = data.get("memory_content", "")
        if not content:
            await callback.answer("Ошибка: нет текста", show_alert=True)
            await state.clear()
            return
        category = await _classify_memory(content)
        await callback.answer(f"Определено: {cat_names.get(category, category)}")
    else:
        await callback.answer(f"Выбрано: {cat_names.get(category, category)}")

    data = await state.get_data()
    content = data.get("memory_content", "")
    if not content:
        await callback.answer("Ошибка: нет текста", show_alert=True)
        await state.clear()
        return

    mid = db.add_memory(callback.from_user.id, category, content)
    await callback.message.answer(
        f"✅ Сохранено: {cat_names.get(category, category)}\n"
        f"#{mid} | {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()
    await callback.answer("Сохранено")


@router.callback_query(F.data == "add_memory")
async def cb_add_memory(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Добавление записи")
    await callback.message.answer(
        "🧠 Что запомнить?\n"
        "Например: я люблю краткие ответы",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_memory_add)
    await state.update_data(memory_category="auto")


@router.callback_query(F.data == "add_reminder")
async def cb_add_reminder(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
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
    await state.clear()
    await callback.answer("Добавление монитора")
    await callback.message.answer(
        "🔍 Название монитора?\n"
        "Например: Google",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_monitor_name)


# Register button handlers for instant FSM routing
_BUTTON_HANDLERS.update({
    "💬 Чат": lambda msg, st: None,
    "🔍 Поиск": lambda msg, st: btn_search(msg, st),
    "⏰ Напомнить": lambda msg, st: btn_remind(msg, st),
    "📋 Задача": lambda msg, st: btn_task(msg, st),
    "📝 Заметка": lambda msg, st: btn_note(msg, st),
    "🧠 Память": lambda msg, st: cmd_memory(msg, st),
    "🌤 Погода": lambda msg, st: btn_weather(msg, st),
    "📊 Отчёт": lambda msg, st: cmd_report(msg),
    "❓ Помощь": lambda msg, st: cmd_help(msg),
})


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Действие отменено.", reply_markup=command_keyboard)
    await callback.answer()


# --- Weather ---

def _weather_emoji(desc: str) -> str:
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
    async with aiohttp.ClientSession() as session:
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

        w_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current="
            f"temperature_2m,relative_humidity_2m,"
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
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🌤 Введи название города:\n"
            "Пример: Moscow",
            reply_markup=cancel_keyboard,
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
        "🌤 Введи название города:\n"
        "Пример: Moscow",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_weather)


async def _process_weather(message: Message, city: str):
    await message.answer(f"🌤 Ищу погоду: {city}...")
    text, error = await get_weather(city)
    if error:
        await message.answer(f"❌ Ошибка погоды: {error}", reply_markup=command_keyboard)
        return
    await message.answer(text, reply_markup=command_keyboard)


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


# --- News ---

@router.message(lambda m: m.text and m.text == "/news")
async def cmd_news(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    await message.answer("📰 Ищу актуальные новости...")

    result, error = await ollama_web_search("последние новости сегодня", max_results=5)
    if error:
        await message.answer(f"❌ {error}", reply_markup=command_keyboard)
        return

    items = result.get("results", [])
    if not items:
        await message.answer("Новостей не найдено.", reply_markup=command_keyboard)
        return

    text = "📰 Актуальные новости:\n\n"
    for i, item in enumerate(items[:5], 1):
        title = item.get("title", "Без названия")
        url = item.get("url", "")
        source = ""
        if url:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace("www.", "")
                source = f" ({domain})"
            except Exception:
                pass
        snippet = _extract_main_text(item.get("content", ""), max_len=200)
        text += f"{i}. {title}{source}\n"
        if snippet:
            text += f"   {snippet}\n"
        if url:
            text += f"   {url}\n"
        text += "\n"

    await message.answer(text[:4096], reply_markup=command_keyboard)


# --- Search ---

@router.message(lambda m: m.text and m.text.startswith("/search"))
async def cmd_search(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🔍 Введи поисковый запрос:\n"
            "Пример: последние новости о Tesla",
            reply_markup=cancel_keyboard,
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
        "🔍 Введи поисковый запрос:\n"
        "Пример: последние новости о Tesla",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_search)


async def _process_search(message: Message, query: str):
    await message.answer(f"🔍 Ищу в интернете: {query}...")

    result, error = await ollama_web_search(query, max_results=5)
    if error:
        await message.answer(f"❌ Ошибка поиска: {error}", reply_markup=command_keyboard)
        return

    if not result or "results" not in result:
        await message.answer("Ничего не найдено.", reply_markup=command_keyboard)
        return

    items = result["results"]
    if not items:
        await message.answer("Ничего не найдено.", reply_markup=command_keyboard)
        return

    text = f"🔍 {query}\n\n"
    for i, item in enumerate(items[:5], 1):
        title = item.get("title", "Без названия")
        url = item.get("url", "")
        snippet = _extract_main_text(item.get("content", ""), max_len=200)
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

    await message.answer(text[:4096], reply_markup=command_keyboard)


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


# --- Fetch ---

@router.message(lambda m: m.text and m.text.startswith("/fetch"))
async def cmd_fetch(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📄 Введи URL для загрузки:\n"
            "Пример: https://example.com/article",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_fetch)
        return

    await _process_fetch(message, parts[1].strip())


async def _process_fetch(message: Message, url: str):
    await message.answer(f"📄 Загружаю: {url}...")

    result, error = await ollama_web_fetch(url)
    if error:
        await message.answer(f"❌ Ошибка загрузки: {error}", reply_markup=command_keyboard)
        return

    title = result.get("title", "Без названия")
    content = result.get("content", "")[:3000]
    links = result.get("links", [])[:10]

    text = f"📄 {title}\n\n{content}\n"
    if links:
        text += "\n🔗 Ссылки на странице:\n"
        for link in links:
            text += f"- {link}\n"

    if len(text) > 4096:
        text = text[:4090] + "..."

    await message.answer(text, reply_markup=command_keyboard)


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


# --- Help ---

async def cmd_help(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    await message.answer(
        "🤖 Вот что я умею:\n\n"
        "🌤 *Погода*\n"
        "• «погода в Москве»\n\n"
        "⏰ *Напоминания*\n"
        "• «напомни через 5 минут позвонить»\n"
        "• «завтра в 9:00 проверить отчёт»\n"
        "• «каждое утро в 9 покажи новости»\n\n"
        "📋 *Задачи (AI выполнит сам)*\n"
        "• «задача каждый день в 7:00 погода в Москве»\n"
        "• «задача через час поищи новости Tesla»\n\n"
        "📝 *Заметки*\n"
        "• «заметка: купить акции TSLA»\n\n"
        "🧠 *Память*\n"
        "• «запомни, я люблю краткие ответы»\n"
        "• «факт: я работаю над проектом X»\n\n"
        "🔍 *Поиск и новости*\n"
        "• «поищи последние новости Tesla»\n"
        "• «новости»\n\n"
        "💬 *AI-чат*\n"
        "• просто напиши вопрос — бот ответит через Ollama\n\n"
        "📋 *Команды:*\n"
        "/start — меню\n"
        "/remind — напоминание\n"
        "/task — задача\n"
        "/note — заметка\n"
        "/memory — память\n"
        "/models — модели\n"
        "/model — сменить модель\n"
        "/clear — очистить историю\n"
        "/monitors — мониторы",
        reply_markup=command_keyboard,
        parse_mode="Markdown",
    )


# Register remaining button handlers (must come after function definitions)
_BUTTON_HANDLERS["❓ Помощь"] = lambda msg, st: cmd_help(msg)
