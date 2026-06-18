import html
import json
import re
from datetime import datetime, timedelta, timezone

import aiohttp
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.inline import (
    memory_menu_keyboard,
    monitor_interval_keyboard,
    note_quick_keyboard,
    reminder_quick_keyboard,
    task_quick_keyboard,
)
from bot.keyboards.reply import cancel_keyboard, command_keyboard
from bot.ollama import OllamaChatMessage, generate_chat_completion
from bot.ollama.dto import OllamaErrorChunk
from bot.security import is_allowed as _is_allowed
from bot.services import reminders as reminders_service
from bot.routers.settings import cmd_settings
from bot.services.profile import format_local
from bot.services.weather import get_forecast, get_weather
from bot.settings import OLLAMA_MODEL, SYSTEM_MESSAGE
from bot.states import BotStates

router = Router()

# Re-export service helpers so existing `from bot.routers.cron import ...` keep working.
_process_remind = reminders_service._process_remind
_process_task_from_text = reminders_service._process_task_from_text

db = None  # injected in __init__


def _user_tz(user_id: int) -> str | None:
    """Look up the user's saved timezone for display + parsing."""
    if db is None:
        return None
    try:
        prefs = db.get_user_prefs(user_id)
    except Exception:
        return None
    return (prefs or {}).get("timezone") or None


def _format_trigger(trigger_at, user_id: int) -> str:
    """Render a stored UTC trigger_at as a human-readable string in the
    user's local timezone. Accepts either a datetime object or an ISO string.
    Returns 'ASAP' if the value is missing or unparseable."""
    if trigger_at is None or trigger_at == "":
        return "ASAP"
    if isinstance(trigger_at, str):
        try:
            trigger_at = datetime.fromisoformat(trigger_at)
        except Exception:
            return trigger_at  # pragma: no cover — show raw if mangled
    return format_local(trigger_at, _user_tz(user_id))

# Known command buttons that should cancel pending FSM input
_COMMAND_BUTTONS = {
    "🔍 Поиск", "⏰ Напомнить", "📋 Задача",
    "📝 Заметка", "📒 Список", "🧠 Память", "📚 База", "🌤 Погода", "📰 Новости",
    "📊 Отчёт", "❓ Помощь", "⚙️ Настройки",
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


# --- Smart time parsing is delegated to bot.services.reminders ---


async def _classify_memory(content: str) -> str:
    """Use Ollama to pick the best memory category for content.

    Falls back to 'note' on timeout, error, or unparseable response so the
    user is never blocked for more than ~10 seconds on classification.
    """
    import asyncio
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
        async with asyncio.timeout(10):
            async for is_done, chunk in generate_chat_completion(messages, OLLAMA_MODEL, temperature=0.2):
                if is_done:
                    break
                if isinstance(chunk, OllamaErrorChunk):
                    break
                result += chunk.message.content
    except asyncio.TimeoutError:
        print("[AUTO MEMORY] Classification timed out — defaulting to 'note'")
        return "note"
    except Exception as e:
        print(f"[AUTO MEMORY] Classification failed: {e}")
    result = result.strip().lower()
    if result in ("fact", "preference", "note"):
        return result
    return "note"


def _refresh_completion_system_prompt(user_id: int) -> None:
    """Best-effort refresh of the live chat's system prompt after the user
    saves a note or memory via cron handlers."""
    try:
        from bot.routers import completion
        completion.refresh_system_prompt(user_id)
    except Exception:
        pass


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

    await reminders_service._process_remind(message.from_user.id, parts[1])


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

    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
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

    db.add_reminder(
        user_id=callback.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="notify",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await callback.message.answer(
        f"✅ Напоминание добавлено\n"
        f"🕐 Сработает: {_format_trigger(trigger_at, callback.from_user.id)}{rec_label}\n"
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
    trigger_at, recurring, parsed = reminders_service.parse_reminder_strict(time_text, tz_name=_user_tz(message.from_user.id))
    if not parsed:
        await message.answer(
            "❓ Не понял время. Примеры: `через 5 минут`, `завтра в 9:00`, `каждый день в 7:00`, `2026-06-15 09:00`.",
            reply_markup=cancel_keyboard,
        )
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    db.add_reminder(
        user_id=message.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="notify",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await message.answer(
        f"✅ Напоминание добавлено\n"
        f"🕐 Сработает: {_format_trigger(trigger_at, message.from_user.id)}{rec_label}\n"
        f"📝 Текст: {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.message(lambda m: m.text and m.text == "/reminders")
@router.message(F.text == "📒 Список")
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
            "📒 Нет активных напоминаний и задач.\n\nДобавь через ⏰ Напомнить или 📋 Задача.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Добавить напоминание", callback_data="add_reminder")],
                ]
            ),
        )
        return

    text = "📒 Активные напоминания и задачи:\n\n"
    buttons = []
    for idx, r in enumerate(reminders, 1):
        time_str = _format_trigger(r.get('trigger_at'), message.from_user.id)
        content = r.get('content', '')
        rec = r.get('recurring')
        is_task = r.get('action') == 'execute'
        mode = "🤖 Задача" if is_task else "⏰ Напоминание"
        rec_label = f" 🔁 {rec}" if rec else ""
        text += f"#{idx} {mode}{rec_label}\n🕐 {time_str}\n📝 {content}\n\n"
        buttons.append([
            InlineKeyboardButton(text=f"✏️ #{idx}", callback_data=f"edit_reminder:{r['id']}"),
            InlineKeyboardButton(text=f"❌ #{idx}", callback_data=f"del_reminder:{r['id']}"),
        ])

    buttons.append([InlineKeyboardButton(text="➕ Добавить напоминание", callback_data="add_reminder")])
    await message.answer(text.strip(), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


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
        await message.answer("✅ Напоминание удалено.", reply_markup=command_keyboard)
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
        await message.answer("✅ Напоминание удалено.", reply_markup=command_keyboard)
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
    trigger_at, recurring, parsed = reminders_service.parse_reminder_strict(time_str, tz_name=_user_tz(message.from_user.id))
    if not parsed:
        await message.answer(
            "❓ Не понял время. Примеры: `через 5 минут`, `завтра в 9:00`, `каждый день в 7:00`, `2026-06-15 09:00`.",
            reply_markup=cancel_keyboard,
        )
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    db.add_reminder(
        user_id=message.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat(),
        recurring=recurring,
        action="execute",
    )
    rec_label = f" ({recurring})" if recurring else ""
    await message.answer(
        f"✅ Задача добавлена\n"
        f"🕐 Сработает: {_format_trigger(trigger_at, message.from_user.id)}{rec_label}\n"
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
        if trigger_at <= now or trigger_at.weekday() >= 5:
            trigger_at += timedelta(days=1)
            while trigger_at.weekday() >= 5:
                trigger_at += timedelta(days=1)
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

    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        await state.clear()
        return
    db.add_reminder(
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
        text=f"✅ Задача добавлена\n"
             f"🕐 Сработает: {_format_trigger(trigger_at, callback.from_user.id)}{rec_label}\n"
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
    _refresh_completion_system_prompt(message.from_user.id)
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
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    db.add_note(message.from_user.id, message.text)
    _refresh_completion_system_prompt(message.from_user.id)
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
    _refresh_completion_system_prompt(message.from_user.id)
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
        r"ежедневно|еженедельно|ежемесячно|по\s+будням|по\s+выходным|по\s+календарю|будни|выходные|рабочие\s+дни",
        r"раз\s+в\s+\d+",
        r"через\s+\d+",
        r"завтра\s+в\s+\d{1,2}:\d{2}",
        r"сегодня\s+в\s+\d{1,2}:\d{2}",
        r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}",
        r"в\s+\d{1,2}:\d{2}",
        r"утра|дн(ём|ем)|вечера|ночи",
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
    _refresh_completion_system_prompt(message.from_user.id)
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
        await callback.answer("Напоминание удалено")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.edit_text("✅ Напоминание удалено.")
    except Exception:
        await callback.answer("Ошибка удаления", show_alert=True)


@router.callback_query(F.data.startswith("edit_reminder:"))
async def cb_edit_reminder(callback: CallbackQuery, state: FSMContext):
    """Show inline menu: edit content vs edit time vs cancel."""
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
    except ValueError:
        await callback.answer("Неверный ID", show_alert=True)
        return
    reminder = db.get_reminder(rid)
    if not reminder or reminder['user_id'] != callback.from_user.id:
        await callback.answer("Нет доступа", show_alert=True)
        return

    is_task = reminder.get('action') == 'execute'
    label = "задачу" if is_task else "напоминание"
    await callback.message.answer(
        f"✏️ Редактировать {label}\n\n"
        f"📝 {reminder.get('content', '')}\n"
        f"🕐 {_format_trigger(reminder.get('trigger_at'), callback.from_user.id)}\n\n"
        f"Что менять?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 Текст", callback_data=f"edit_rcontent:{rid}")],
                [InlineKeyboardButton(text="🕐 Время", callback_data=f"edit_rtime:{rid}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_rcontent:"))
async def cb_edit_reminder_content(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rid = int(callback.data.split(":", 1)[1])
    await state.update_data(edit_reminder_id=rid)
    await state.set_state(BotStates.waiting_remind_edit_content)
    await callback.message.answer(
        "📝 Введи новый текст:",
        reply_markup=cancel_keyboard,
    )
    await callback.answer("Введи новый текст")


@router.callback_query(F.data.startswith("edit_rtime:"))
async def cb_edit_reminder_time(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.data:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rid = int(callback.data.split(":", 1)[1])
    await state.update_data(edit_reminder_id=rid)
    await state.set_state(BotStates.waiting_remind_edit_time)
    await callback.message.answer(
        "🕐 Введи новое время:\n"
        "Примеры: «через 5 минут», «завтра в 9:00», «каждый день в 7:00», «2026-06-15 09:00»",
        reply_markup=cancel_keyboard,
    )
    await callback.answer("Введи новое время")


@router.message(BotStates.waiting_remind_edit_content)
async def process_edit_reminder_content(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    data = await state.get_data()
    rid = data.get("edit_reminder_id")
    reminder = db.get_reminder(rid) if rid else None
    if not reminder or reminder['user_id'] != message.from_user.id:
        await message.answer("Нет доступа к этой записи.", reply_markup=command_keyboard)
        await state.clear()
        return
    new_content = message.text.strip()
    if not new_content:
        await message.answer("Текст не может быть пустым.", reply_markup=cancel_keyboard)
        return
    db.update_reminder_content(rid, new_content)
    await message.answer(
        f"✅ Обновлено\n📝 {new_content}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.message(BotStates.waiting_remind_edit_time)
async def process_edit_reminder_time(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        await state.clear()
        return
    data = await state.get_data()
    rid = data.get("edit_reminder_id")
    reminder = db.get_reminder(rid) if rid else None
    if not reminder or reminder['user_id'] != message.from_user.id:
        await message.answer("Нет доступа к этой записи.", reply_markup=command_keyboard)
        await state.clear()
        return
    trigger_at, recurring, parsed = reminders_service.parse_reminder_strict(message.text.strip(), tz_name=_user_tz(message.from_user.id))
    if not parsed:
        await message.answer(
            "❓ Не понял время. Примеры: «через 5 минут», «завтра в 9:00», «каждый день в 7:00».",
            reply_markup=cancel_keyboard,
        )
        return
    db.update_reminder_schedule(rid, trigger_at.isoformat(), recurring)
    rec_label = f" 🔁 {recurring}" if recurring else ""
    await message.answer(
        f"✅ Обновлено\n🕐 {_format_trigger(trigger_at, message.from_user.id)}{rec_label}",
        reply_markup=command_keyboard,
    )
    await state.clear()


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
    except Exception:
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
    except Exception:
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
    _refresh_completion_system_prompt(callback.from_user.id)
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
    "⚙️ Настройки": lambda msg, st: cmd_settings(msg, st),
})


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Действие отменено.", reply_markup=command_keyboard)
    await callback.answer()


# --- Weather ---


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
            "Пример: Москва\n"
            "Или прогноз: «Москва на неделю», «Сочи 5 дней», «Москва месяц»",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_weather)
        return

    await _process_weather(message, parts[1].strip())


@router.message(F.text == "🌤 Погода")
async def btn_weather(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    await message.answer(
        "🌤 Введи название города:\n"
        "Пример: Москва\n"
        "Или прогноз: «Москва на неделю», «Сочи 5 дней», «Москва месяц»",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_weather)


async def _process_weather(message: Message, raw: str):
    """Handle both '/weather Moscow' and '/weather Moscow на неделю'.
    Strips trailing duration phrases from the city, then routes to
    get_forecast or get_weather depending on intent."""
    from bot.intent.tools.weather import _FORECAST_PHRASE_RE, _detect_days

    raw = (raw or "").strip()
    days = _detect_days(raw)
    is_forecast = bool(days) or bool(_FORECAST_PHRASE_RE.search(raw))

    # Strip trailing duration / forecast phrases so 'Москва на неделю'
    # leaves just 'Москва' as the city.
    city = re.sub(
        r"\s*(?:на\s+)?(?:неделю|неделя|месяц|выходные|завтра|послезавтра|"
        r"ближайш\w*|прогноз\w*|forecast|this\s+week|this\s+month|tomorrow|"
        r"\d+\s*(?:день|дня|дней|сутки|суток)|next\s+\d+\s+days?)\s*",
        " ",
        raw,
        flags=re.IGNORECASE,
    ).strip(" ,.;-—")

    if not city:
        await message.answer("🌤 Не понял город. Пример: Москва", reply_markup=command_keyboard)
        return

    label = "прогноз" if is_forecast else "погоду"
    await message.answer(f"🌤 Ищу {label}: {city}...")
    if is_forecast:
        text, error = await get_forecast(city, days or 7)
    else:
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


# --- Knowledge base search ---


@router.message(lambda m: m.text and m.text.startswith("/kb"))
async def cmd_kb(message: Message, state: FSMContext):
    """`/kb <query>` searches the user's KB; bare `/kb` asks for a query."""
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📚 Что найти в базе?\n"
            "Например: «Tesla», «Армения», «отчёт о проекте».\n"
            "Если ничего не найду локально — посмотрю в интернете.",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_kb)
        return
    await _process_kb(message, parts[1].strip())


@router.message(F.text == "📚 База")
async def btn_kb(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    await message.answer(
        "📚 Что найти в базе?\n"
        "Например: «Tesla», «Армения», «отчёт о проекте».\n"
        "Если ничего не найду локально — посмотрю в интернете.",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_kb)


@router.message(BotStates.waiting_kb)
async def process_kb(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    await _process_kb(message, message.text.strip())
    await state.clear()


async def _process_kb(message: Message, query: str):
    if not query:
        await message.answer("Введи поисковый запрос.", reply_markup=cancel_keyboard)
        return
    from bot.services.kb import search_kb_with_web_fallback
    text, hits, used_web = await search_kb_with_web_fallback(
        message.from_user.id, query, limit=5
    )
    if not text:
        await message.answer(
            f"📚 Ни в твоей базе, ни в интернете ничего по «{query}» не нашёл.",
            reply_markup=command_keyboard,
        )
        return
    await message.answer(text, reply_markup=command_keyboard)


# --- Knowledge base end ---


# --- News ---

def _format_search_results(query: str, items: list[dict]) -> str:
    """Render Ollama web-search results in the same clean style as RSS news."""
    text = f"🔍 {query}\n\n"
    for i, item in enumerate(items[:5], 1):
        title = item.get("title", "Без названия").strip()
        url = item.get("url", "").strip()
        snippet = _extract_main_text(item.get("content", ""), max_len=220)
        source = ""
        if url:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace("www.", "")
                if domain:
                    source = f"🌐 {domain}"
            except Exception:
                pass

        text += f"{i}. {title}\n"
        if source:
            text += f"   {source}\n"
        if snippet:
            text += f"   {snippet}\n"
        if url:
            text += f"   🔗 {url}\n"
        text += "\n"
    return text[:4096]


async def _process_news(message: Message, topic: str | None = None):
    """Fetch fresh news: RSS-first, then web-search fallback.

    RSS gives us curated, recent sources; if nothing matches the topic or
    the feeds are stale we fall back to DuckDuckGo/SearXNG/Ollama depending on
    the WEB_SEARCH_PROVIDER setting.
    """
    if message.from_user is None:
        return
    user_id = message.from_user.id
    label = topic.strip() if topic and topic.strip() else "топ-новости"
    await message.answer(f"📰 Ищу новости: {label}...")

    from bot.services.rss_news import get_fresh_news
    text, items, source = await get_fresh_news(user_id, topic=topic, limit=5)
    if not text:
        await message.answer(
            f"Новостей по запросу «{label}» не найдено.",
            reply_markup=command_keyboard,
        )
        return

    footer = f"\n\n(источник: {source})" if source else ""
    full_text = text + footer
    if len(full_text) > 4096:
        full_text = full_text[:4090] + "..."
    await message.answer(full_text, reply_markup=command_keyboard)


async def _process_digest(message: Message):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    await message.answer("📰 Собираю персональный дайджест...")

    from bot.services.news_categories import get_personalized_digest
    text = await get_personalized_digest(user_id)
    await message.answer(text, reply_markup=command_keyboard)


@router.message(lambda m: m.text and m.text.startswith("/news"))
async def cmd_news(message: Message, state: FSMContext):
    """`/news` alone → ask for topic. `/news <topic>` → search immediately."""
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📰 По какой теме новости?\n"
            "Например: «ИИ», «Tesla», «биткоин», «спорт»\n"
            "Или «дайджест» — персональная подборка по категориям.\n"
            "Или просто «топ» — покажу самое актуальное.",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_news)
        return
    await _process_news(message, parts[1])


@router.message(F.text == "📰 Новости")
async def btn_news(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    await message.answer(
        "📰 По какой теме новости?\n"
        "Например: «ИИ», «Tesla», «биткоин», «спорт»\n"
        "Или «дайджест» — персональная подборка по категориям.\n"
        "Или просто «топ» — покажу самое актуальное.",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_news)


@router.message(BotStates.waiting_news)
async def process_news(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    if await _fsm_guard(message, state):
        return
    topic = message.text.strip()
    lowered = topic.lower()
    if lowered in ("топ", "top", ""):
        topic = None
        await _process_news(message, topic)
    elif lowered in ("дайджест", "digest", "мои", "подписки"):
        await _process_digest(message)
    else:
        await _process_news(message, topic)
    await state.clear()


@router.message(lambda m: m.text and m.text.startswith("/news_subscribe"))
async def cmd_news_subscribe(message: Message, state: FSMContext):
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
            "📰 Какую категорию добавить?\n"
            "tech, markets, ai, science, crypto, world",
            reply_markup=cancel_keyboard,
        )
        return

    from bot.services.news_categories import add_user_category
    cats, added = add_user_category(message.from_user.id, parts[1])
    if added:
        await message.answer(
            f"✅ Добавлено. Твои категории: {', '.join(cats)}",
            reply_markup=command_keyboard,
        )
    else:
        await message.answer(
            f"⚠️ Уже есть или неизвестная категория. Текущие: {', '.join(cats)}",
            reply_markup=command_keyboard,
        )


@router.message(lambda m: m.text and m.text.startswith("/news_unsubscribe"))
async def cmd_news_unsubscribe(message: Message, state: FSMContext):
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
            "📰 Какую категорию убрать?\n"
            "tech, markets, ai, science, crypto, world",
            reply_markup=cancel_keyboard,
        )
        return

    from bot.services.news_categories import remove_user_category
    cats, removed = remove_user_category(message.from_user.id, parts[1])
    if removed:
        await message.answer(
            f"✅ Убрано. Твои категории: {', '.join(cats)}",
            reply_markup=command_keyboard,
        )
    else:
        await message.answer(
            f"⚠️ Категории не было в подписках. Текущие: {', '.join(cats)}",
            reply_markup=command_keyboard,
        )


@router.message(lambda m: m.text and m.text == "/docs")
async def cmd_docs(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    from bot.services import documents as documents_service
    docs = documents_service.get_user_documents(message.from_user.id)
    if not docs:
        await message.answer(
            "📄 Нет сохранённых документов.\n\nПросто пришли мне PDF, TXT или DOCX.",
            reply_markup=command_keyboard,
        )
        return

    lines = ["📄 Твои документы:"]
    for idx, doc in enumerate(docs, 1):
        created = doc.get("created_at", "")
        lines.append(f"#{idx} ID {doc['id']}: {doc['filename']} ({created})")
    lines.append("\nУдалить: /forget_doc <id>")
    await message.answer("\n".join(lines), reply_markup=command_keyboard)


@router.message(lambda m: m.text and m.text.startswith("/forget_doc"))
async def cmd_forget_doc(message: Message, state: FSMContext):
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
            "❌ Введи ID документа:\n"
            "Пример: /forget_doc 3\n\n"
            "Список документов: /docs",
            reply_markup=command_keyboard,
        )
        return

    try:
        doc_id = int(parts[1])
    except ValueError:
        await message.answer("Укажи числовой ID документа.", reply_markup=command_keyboard)
        return

    from bot.services import documents as documents_service
    doc = documents_service.get_document(doc_id)
    if not doc or doc.get("user_id") != message.from_user.id:
        await message.answer("⚠️ Документ не найден или нет доступа.", reply_markup=command_keyboard)
        return

    if documents_service.delete_document(doc_id):
        await message.answer(
            f"✅ Документ *{doc['filename']}* удалён.",
            reply_markup=command_keyboard,
            parse_mode="Markdown",
        )
    else:
        await message.answer("⚠️ Не удалось удалить документ.", reply_markup=command_keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith("suggest:"))
async def cb_suggest(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not callback.from_user:
        return
    user_id = callback.from_user.id
    if not _is_allowed(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if db is None:
        await callback.answer("База данных недоступна", show_alert=True)
        return

    data = callback.data
    if data == "suggest:dismiss":
        await callback.message.edit_text("👌 Хорошо, не сохраняю.")
        await callback.answer("Отклонено")
        return

    from bot.services import reminder_suggest as reminder_suggest_service
    parts = data.split(":", 4)
    if len(parts) < 3:
        await callback.answer("Ошибка данных", show_alert=True)
        return
    _prefix, item_type, _idx = parts[0], parts[1], parts[2]
    content = parts[3] if len(parts) > 3 else ""
    time_text = parts[4] if len(parts) > 4 else ""

    if item_type == "reminder":
        result = await reminder_suggest_service.create_reminder(user_id, content, time_text)
    elif item_type == "task":
        result = await reminder_suggest_service.create_task(user_id, content, time_text)
    else:
        result = await reminder_suggest_service.create_note(user_id, content)

    await callback.message.edit_text(result, reply_markup=command_keyboard)
    await callback.answer("Сохранено")


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
    await state.clear()
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

    text = _format_search_results(query, items)
    await message.answer(text, reply_markup=command_keyboard)


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


# Register remaining button handlers (must come after function definitions).
# These let _fsm_guard route a button press to the right flow instead of
# falling back to "press the button again".
_BUTTON_HANDLERS["❓ Помощь"] = lambda msg, st: cmd_help(msg)
_BUTTON_HANDLERS["⏰ Напомнить"] = btn_remind
_BUTTON_HANDLERS["📋 Задача"] = btn_task
_BUTTON_HANDLERS["📝 Заметка"] = btn_note
_BUTTON_HANDLERS["🧠 Память"] = cmd_memory
_BUTTON_HANDLERS["📚 База"] = btn_kb
_BUTTON_HANDLERS["🌤 Погода"] = btn_weather
_BUTTON_HANDLERS["🔍 Поиск"] = btn_search
_BUTTON_HANDLERS["📰 Новости"] = btn_news
_BUTTON_HANDLERS["📊 Отчёт"] = cmd_report
_BUTTON_HANDLERS["📒 Список"] = cmd_reminders
