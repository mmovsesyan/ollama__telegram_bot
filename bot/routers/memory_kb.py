import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.keyboards.inline import (
    memory_filter_keyboard,
    memory_menu_keyboard,
    memory_pagination_keyboard,
)
from bot.keyboards.reply import cancel_keyboard, command_keyboard
from bot.security import is_allowed as _is_allowed
from bot.states import BotStates
from bot.routers.common import (
    _BUTTON_HANDLERS,
    _classify_memory,
    _fsm_guard,
    _refresh_completion_system_prompt,
    _typing_until,
)

router = Router()
logger = logging.getLogger(__name__)

# Injected from bot/__init__.py at startup.
db = None


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
            "🧠 Что запомнить?\n" "Например: я люблю краткие ответы",
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
    cat_names = {
        "fact": "📌 Факт",
        "preference": "❤️ Предпочтение",
        "note": "📝 Заметка",
    }
    await message.answer(
        f"✅ Сохранено: {cat_names.get(category, category)}\n" f"#{mid} | {content}",
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
    cat_names = {
        "fact": "📌 Факт",
        "preference": "❤️ Предпочтение",
        "note": "📝 Заметка",
    }

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
        f"✅ Сохранено: {cat_names.get(category, category)}\n" f"#{mid} | {content}",
        reply_markup=command_keyboard,
    )
    await state.clear()


@router.message(
    lambda m: m.text
    and (m.text == "/memory_summary" or m.text.startswith("/memory_summary"))
)
async def cmd_memory_summary(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    await message.answer("🧠 Готовлю профиль на основе памяти...")
    await _send_memory_summary(message.from_user.id, message)


@router.message(
    lambda m: m.text and (m.text == "/cleanup" or m.text.startswith("/cleanup"))
)
async def cmd_cleanup(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return
    from bot.services import retention as retention_service

    docs, images = retention_service.cleanup_user_retention(message.from_user.id)
    await message.answer(
        f"🗑 Очистка завершена:\n"
        f"Документов удалено: {docs}\n"
        f"Фото удалено: {images}",
        reply_markup=command_keyboard,
    )


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
            "🗑 Введи ID факта для удаления:\n" "Пример: 5",
            reply_markup=cancel_keyboard,
        )
        await state.set_state(BotStates.waiting_memory_remove)
        return

    try:
        mid = int(parts[1])
        user_memories = db.get_memories(message.from_user.id)
        if not any(m["id"] == mid for m in user_memories):
            await message.answer(
                "Нет доступа к этому факту.", reply_markup=command_keyboard
            )
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
        if not any(m["id"] == mid for m in user_memories):
            await message.answer(
                "Нет доступа к этому факту.", reply_markup=cancel_keyboard
            )
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

    if action == "summary":
        await callback.answer("Готовлю профиль...")
        await _send_memory_summary(callback.from_user.id, callback.message)
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
            "📌 Какой факт сохранить?\n" "Например: я работаю над проектом X",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Добавляем факт")
        return

    if action == "add_preference":
        await state.set_state(BotStates.waiting_memory_add)
        await state.update_data(memory_category="preference")
        await callback.message.answer(
            "❤️ Какое предпочтение сохранить?\n" "Например: я люблю краткие ответы",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Добавляем предпочтение")
        return

    if action == "add_note":
        await state.set_state(BotStates.waiting_memory_add)
        await state.update_data(memory_category="note")
        await callback.message.answer(
            "📝 Какую заметку сохранить?\n" "Например: купить акции TSLA",
            reply_markup=cancel_keyboard,
        )
        await callback.answer("Добавляем заметку")
        return


MEMORY_PAGE_SIZE = 5
MAX_MEMORY_ITEM_LENGTH = 300


def _format_memory_item(idx: int, memory: dict) -> str:
    cat_names = {
        "fact": "📌 Факт",
        "preference": "❤️ Предпочтение",
        "note": "📝 Заметка",
        "task": "📋 Задача",
        "decision": "⚖️ Решение",
    }
    cat = memory.get("category", "fact")
    content = memory.get("content", "")
    text = (
        content
        if len(content) <= MAX_MEMORY_ITEM_LENGTH
        else content[:MAX_MEMORY_ITEM_LENGTH].rsplit(" ", 1)[0] + "..."
    )
    return f"#{idx} | {cat_names.get(cat, cat)}\n{text}"


def _filter_memories(memories: list[dict], category: str | None) -> list[dict]:
    if not category or category == "all":
        return memories
    return [m for m in memories if m.get("category", "fact") == category]


async def _show_memories(
    user_id: int,
    message: Message,
    page: int = 0,
    category: str = "all",
    edit: bool = False,
):
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return
    all_memories = db.get_memories(user_id)
    filtered = _filter_memories(all_memories, category)
    if not filtered:
        text = (
            "Нет сохранённых записей."
            if category == "all"
            else f"Нет записей категории «{category}»."
        )
        if edit and message.text is not None:
            try:
                await message.edit_text(text, reply_markup=memory_menu_keyboard())
            except Exception:
                await message.answer(text, reply_markup=memory_menu_keyboard())
        else:
            await message.answer(text, reply_markup=memory_menu_keyboard())
        return

    total_pages = max(1, (len(filtered) + MEMORY_PAGE_SIZE - 1) // MEMORY_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * MEMORY_PAGE_SIZE
    page_memories = filtered[start : start + MEMORY_PAGE_SIZE]

    lines = ["🧠 Память:", ""]
    buttons: list[list[InlineKeyboardButton]] = []
    global_idx = start
    for m in page_memories:
        global_idx += 1
        lines.append(_format_memory_item(global_idx, m))
        lines.append("")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 Удалить #{global_idx}",
                    callback_data=f"del_memory:{m['id']}",
                )
            ]
        )

    keyboard_rows = buttons + memory_filter_keyboard(category).inline_keyboard
    paginator = memory_pagination_keyboard(page, total_pages, category)
    if paginator:
        keyboard_rows.extend(paginator.inline_keyboard)
    keyboard_rows.append(
        [InlineKeyboardButton(text="➕ Добавить", callback_data="memory_menu:add_auto")]
    )

    text = "\n".join(lines).strip()
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    if edit and message.text is not None:
        try:
            await message.edit_text(text, reply_markup=markup)
        except Exception:
            await message.answer(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


async def _send_memory_summary(user_id: int, message: Message):
    from bot.services.kb import summarize_kb

    text = await _typing_until(user_id, summarize_kb(user_id))
    await message.answer(text, reply_markup=memory_menu_keyboard())


@router.callback_query(F.data.startswith("mem_page:"))
async def cb_memory_page(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split(":")
    try:
        page = int(parts[1])
        category = parts[2] if len(parts) > 2 else "all"
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return
    await _show_memories(
        callback.from_user.id, callback.message, page=page, category=category, edit=True
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mem_filter:"))
async def cb_memory_filter(callback: CallbackQuery):
    if not callback.from_user or not callback.message:
        return
    if not _is_allowed(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    category = callback.data.split(":", 1)[1] or "all"
    await _show_memories(
        callback.from_user.id, callback.message, page=0, category=category, edit=True
    )
    await callback.answer(f"Фильтр: {category}")


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
        if not any(m["id"] == mid for m in user_memories):
            await callback.answer("Нет доступа", show_alert=True)
            return
        db.remove_memory(mid)
        await callback.answer(f"Запись #{mid} удалена")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc:
            logger.warning(
                "Failed to clear memory delete markup for %s: %s",
                callback.from_user.id,
                exc,
            )
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
    cat_names = {
        "fact": "📌 Факт",
        "preference": "❤️ Предпочтение",
        "note": "📝 Заметка",
    }

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
        f"✅ Сохранено: {cat_names.get(category, category)}\n" f"#{mid} | {content}",
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
        "🧠 Что запомнить?\n" "Например: я люблю краткие ответы",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BotStates.waiting_memory_add)
    await state.update_data(memory_category="auto")


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
    if message.from_user is None:
        return
    user_id = message.from_user.id
    from bot.services.kb import search_kb_with_web_fallback

    await message.answer("📚 Ищу в базе и интернете...")
    text, hits, used_web = await _typing_until(
        user_id, search_kb_with_web_fallback(user_id, query, limit=5)
    )
    if not text:
        await message.answer(
            f"📚 Ни в твоей базе, ни в интернете ничего по «{query}» не нашёл.",
            reply_markup=command_keyboard,
        )
        return
    await message.answer(text, reply_markup=command_keyboard)


_BUTTON_HANDLERS.update(
    {
        "🧠 Память": lambda msg, st: cmd_memory(msg, st),
        "📚 База": lambda msg, st: btn_kb(msg, st),
    }
)
