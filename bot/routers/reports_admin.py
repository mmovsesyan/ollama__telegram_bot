import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.bot import bot as aiogram_bot
from bot.keyboards.reply import command_keyboard
from bot.security import is_admin, is_allowed as _is_allowed
from bot.routers.common import _BUTTON_HANDLERS
from bot.routers.settings import cmd_settings

router = Router()
logger = logging.getLogger(__name__)

# Injected from bot/__init__.py at startup.
db = None


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

    user_id = message.from_user.id
    try:
        await aiogram_bot.send_chat_action(chat_id=user_id, action="typing")
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    text = f"📊 Ежедневный отчёт ({now.strftime('%Y-%m-%d %H:%M')})\n\n"

    reminders = db.get_user_reminders(user_id)
    text += f"⏰ Напоминаний / задач: {len(reminders)}\n"

    monitors = db.get_monitors(user_id)
    text += f"🔍 Мониторов: {len(monitors)}\n"

    notes = db.get_notes(user_id)
    if notes:
        text += f"\n📝 Заметки:\n{notes}"

    memories = db.get_memories(user_id)
    if memories:
        text += f"\n🧠 Память: {len(memories)} фактов"

    await message.answer(text, reply_markup=command_keyboard)


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
        "/monitors — мониторы\n\n"
        "🛡 *Администратору:*\n"
        "/admin_requests — запросы на доступ\n"
        "/admin_approve <id> — одобрить\n"
        "/admin_reject <id> — отклонить\n"
        "/admin_remove <id> — удалить пользователя\n"
        "/admin_list — список пользователей\n"
        "/admin_promote <id> — сделать админом\n"
        "/admin_demote <id> — снять админа",
        reply_markup=command_keyboard,
        parse_mode="Markdown",
    )


# --- Smart suggestion callbacks ---


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
        result = await reminder_suggest_service.create_reminder(
            user_id, content, time_text
        )
    elif item_type == "task":
        result = await reminder_suggest_service.create_task(user_id, content, time_text)
    else:
        result = await reminder_suggest_service.create_note(user_id, content)

    await callback.message.edit_text(result, reply_markup=command_keyboard)
    await callback.answer("Сохранено")


# --- Documents / images helpers ---


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
        await message.answer(
            "Укажи числовой ID документа.", reply_markup=command_keyboard
        )
        return

    from bot.services import documents as documents_service

    doc = documents_service.get_document(doc_id, user_id=message.from_user.id)
    if not doc:
        await message.answer(
            "⚠️ Документ не найден или нет доступа.", reply_markup=command_keyboard
        )
        return

    if documents_service.delete_document(doc_id, user_id=message.from_user.id):
        await message.answer(
            f"✅ Документ *{doc['filename']}* удалён.",
            reply_markup=command_keyboard,
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            "⚠️ Не удалось удалить документ.", reply_markup=command_keyboard
        )


@router.message(lambda m: m.text and m.text == "/images")
async def cmd_images(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        return
    if db is None:
        await message.answer("База данных недоступна.", reply_markup=command_keyboard)
        return

    from bot.services import images as images_service

    images = images_service.get_user_images(message.from_user.id)
    if not images:
        await message.answer(
            "📷 Нет сохранённых фото.\n\nПросто пришли мне изображение.",
            reply_markup=command_keyboard,
        )
        return

    lines = ["📷 Твои фото:"]
    for idx, img in enumerate(images, 1):
        created = img.get("created_at", "")
        caption = img.get("caption") or ""
        desc = (img.get("description") or "")[:60]
        header = f"#{idx} ID {img['id']}"
        if caption:
            header += f": {caption}"
        lines.append(f"{header}\n   {desc}... ({created})")
    lines.append("\nУдалить: /forget_image <id>")
    await message.answer("\n".join(lines), reply_markup=command_keyboard)


@router.message(lambda m: m.text and m.text.startswith("/forget_image"))
async def cmd_forget_image(message: Message, state: FSMContext):
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
            "❌ Введи ID фото:\n" "Пример: /forget_image 3\n\n" "Список фото: /images",
            reply_markup=command_keyboard,
        )
        return

    try:
        image_id = int(parts[1])
    except ValueError:
        await message.answer("Укажи числовой ID фото.", reply_markup=command_keyboard)
        return

    from bot.services import images as images_service

    img = images_service.get_image(image_id, user_id=message.from_user.id)
    if not img:
        await message.answer(
            "⚠️ Фото не найдено или нет доступа.", reply_markup=command_keyboard
        )
        return

    if images_service.delete_image(image_id, user_id=message.from_user.id):
        await message.answer(
            f"✅ Фото ID {image_id} удалёно.",
            reply_markup=command_keyboard,
        )
    else:
        await message.answer(
            "⚠️ Не удалось удалить фото.", reply_markup=command_keyboard
        )


# --- Admin user management ---


async def _admin_required(message: Message) -> bool:
    """Check that the caller is an approved admin and give clear feedback if not."""
    if message.from_user is None:
        return False
    user_id = message.from_user.id

    if not _is_allowed(user_id):
        await message.answer(
            "⛔ У тебя нет доступа к боту. Обратись к администратору.",
            reply_markup=command_keyboard,
        )
        logger.warning("[ADMIN] non-allowed user %s tried admin command", user_id)
        return False

    if not is_admin(user_id):
        await message.answer(
            "🛡 Эта команда только для администраторов.",
            reply_markup=command_keyboard,
        )
        logger.warning("[ADMIN] non-admin user %s tried admin command", user_id)
        return False

    return True


def _format_user_row(idx: int, user: dict) -> str:
    status_emoji = {
        "pending": "⏳",
        "approved": "✅",
        "rejected": "❌",
        "blocked": "🚫",
    }.get(user.get("status", "pending"), "❓")
    admin_mark = " 👑" if user.get("is_admin") else ""
    name = user.get("full_name") or user.get("username") or f"ID {user['user_id']}"
    return f"{idx}. {status_emoji} `{user['user_id']}` — {name}{admin_mark}"


@router.message(lambda m: m.text and m.text.startswith("/admin_requests"))
async def cmd_admin_requests(message: Message, state: FSMContext):
    await state.clear()
    if not await _admin_required(message):
        return

    pending = db.get_users_by_status("pending") if db else []
    if not pending:
        await message.answer(
            "Нет запросов на доступ.",
            reply_markup=command_keyboard,
        )
        return

    lines = ["🛡 Запросы на доступ:"]
    for i, user in enumerate(pending, 1):
        lines.append(_format_user_row(i, user))

    await message.answer(
        "\n".join(lines),
        reply_markup=command_keyboard,
        parse_mode="Markdown",
    )


@router.message(lambda m: m.text and m.text.startswith("/admin_list"))
async def cmd_admin_list(message: Message, state: FSMContext):
    await state.clear()
    if not await _admin_required(message):
        return

    users = db.get_all_users() if db else []
    if not users:
        await message.answer(
            "В базе пока нет пользователей.",
            reply_markup=command_keyboard,
        )
        return

    lines = ["👥 Пользователи:"]
    for i, user in enumerate(users, 1):
        lines.append(_format_user_row(i, user))

    await message.answer(
        "\n".join(lines),
        reply_markup=command_keyboard,
        parse_mode="Markdown",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("admin:"))
async def cb_admin_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user is None:
        await callback.answer("Ошибка.")
        return
    if not _is_allowed(callback.from_user.id) or not is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректная команда.")
        return
    _, action, target_id_str = parts
    try:
        target_id = int(target_id_str)
    except ValueError:
        await callback.answer("Некорректный ID.")
        return

    if action not in ("approve", "reject"):
        await callback.answer("Неизвестное действие.")
        return

    target = db.get_user(target_id) if db else None
    if target is None:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return

    new_status = "approved" if action == "approve" else "rejected"
    ok = (
        db.set_user_status(target_id, new_status, approved_by=callback.from_user.id)
        if db
        else False
    )
    if not ok:
        await callback.answer("Не удалось обновить статус.", show_alert=True)
        return

    await callback.answer("Готово")
    await callback.message.edit_reply_markup(reply_markup=None)

    display = target.get("full_name") or target.get("username") or f"ID {target_id}"
    await callback.message.answer(
        f"{'✅' if action == 'approve' else '❌'} Пользователь {display} (`{target_id}`) — {new_status}.",
        parse_mode="Markdown",
    )

    try:
        await callback.bot.send_message(
            chat_id=target_id,
            text=(
                "✅ Доступ одобрен! Напиши /start, чтобы начать."
                if action == "approve"
                else "⛔ Доступ отклонён."
            ),
        )
    except Exception as e:
        logger.warning("[ADMIN] notify target failed: %s", e)


async def _admin_set_status(message: Message, state: FSMContext, status: str):
    await state.clear()
    if not await _admin_required(message):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            f"Укажи ID пользователя: /admin_{status} <id>",
            reply_markup=command_keyboard,
        )
        return
    try:
        target_id = int(parts[1].strip())
    except ValueError:
        await message.answer("ID должен быть числом.", reply_markup=command_keyboard)
        return

    if target_id == message.from_user.id and status in ("rejected", "blocked"):
        await message.answer(
            "Нельзя применить это к себе.",
            reply_markup=command_keyboard,
        )
        return

    target = db.get_user(target_id) if db else None
    if target is None:
        await message.answer(
            "Пользователь не найден.",
            reply_markup=command_keyboard,
        )
        return

    previous_status = target.get("status")

    ok = (
        db.set_user_status(target_id, status, approved_by=message.from_user.id)
        if db
        else False
    )
    if not ok:
        await message.answer(
            "Не удалось обновить статус.", reply_markup=command_keyboard
        )
        return

    display = target.get("full_name") or target.get("username") or f"ID {target_id}"
    await message.answer(
        f"{'✅' if status == 'approved' else '❌' if status == 'rejected' else '🚫'} "
        f"Пользователь {display} (`{target_id}`) — {status}.",
        reply_markup=command_keyboard,
        parse_mode="Markdown",
    )

    # Notify target user, but only when the status actually changed. If the
    # user was already approved, sending the welcome message again is confusing.
    if previous_status == status:
        return

    try:
        await message.bot.send_message(
            chat_id=target_id,
            text=(
                "✅ Доступ одобрен! Напиши /start, чтобы начать."
                if status == "approved"
                else "⛔ Доступ отклонён."
                if status == "rejected"
                else "🚫 Доступ заблокирован."
            ),
        )
    except Exception as e:
        logger.warning("[ADMIN] notify target failed: %s", e)


@router.message(lambda m: m.text and m.text.startswith("/admin_approve"))
async def cmd_admin_approve(message: Message, state: FSMContext):
    await _admin_set_status(message, state, "approved")


@router.message(lambda m: m.text and m.text.startswith("/admin_reject"))
async def cmd_admin_reject(message: Message, state: FSMContext):
    await _admin_set_status(message, state, "rejected")


@router.message(lambda m: m.text and m.text.startswith("/admin_block"))
async def cmd_admin_block(message: Message, state: FSMContext):
    await _admin_set_status(message, state, "blocked")


@router.message(lambda m: m.text and m.text.startswith("/admin_remove"))
async def cmd_admin_remove(message: Message, state: FSMContext):
    await state.clear()
    if not await _admin_required(message):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Укажи ID пользователя: /admin_remove <id>",
            reply_markup=command_keyboard,
        )
        return
    try:
        target_id = int(parts[1].strip())
    except ValueError:
        await message.answer("ID должен быть числом.", reply_markup=command_keyboard)
        return

    if target_id == message.from_user.id:
        await message.answer(
            "Нельзя удалить самого себя.",
            reply_markup=command_keyboard,
        )
        return

    target = db.get_user(target_id) if db else None
    if target is None:
        await message.answer(
            "Пользователь не найден.",
            reply_markup=command_keyboard,
        )
        return

    ok = db.delete_user(target_id) if db else False
    if not ok:
        await message.answer(
            "Не удалось удалить пользователя.",
            reply_markup=command_keyboard,
        )
        return

    # Drop any in-memory chat/session state for the removed user so they can't
    # keep interacting with cached context even if their DB record is gone.
    try:
        from bot.routers import completion

        completion._delete_chat(target_id)
    except Exception as exc:
        logger.warning("Failed to drop in-memory chat for %s: %s", target_id, exc)

    await message.answer(
        f"🗑 Пользователь `{target_id}` и все его данные удалены.",
        reply_markup=command_keyboard,
        parse_mode="Markdown",
    )


async def _admin_set_admin(message: Message, state: FSMContext, is_admin_flag: bool):
    await state.clear()
    if not await _admin_required(message):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            f"Укажи ID: /admin_{'promote' if is_admin_flag else 'demote'} <id>",
            reply_markup=command_keyboard,
        )
        return
    try:
        target_id = int(parts[1].strip())
    except ValueError:
        await message.answer("ID должен быть числом.", reply_markup=command_keyboard)
        return

    if target_id == message.from_user.id and not is_admin_flag:
        await message.answer(
            "Нельзя снять админ-права с самого себя.",
            reply_markup=command_keyboard,
        )
        return

    target = db.get_user(target_id) if db else None
    if target is None:
        await message.answer("Пользователь не найден.", reply_markup=command_keyboard)
        return

    ok = db.set_user_admin(target_id, is_admin_flag) if db else False
    if not ok:
        await message.answer(
            "Не удалось обновить права.", reply_markup=command_keyboard
        )
        return

    await message.answer(
        f"{'👑' if is_admin_flag else '👤'} Пользователь `{target_id}` — "
        f"{'админ' if is_admin_flag else 'обычный пользователь'}.",
        reply_markup=command_keyboard,
        parse_mode="Markdown",
    )


@router.message(lambda m: m.text and m.text.startswith("/admin_promote"))
async def cmd_admin_promote(message: Message, state: FSMContext):
    await _admin_set_admin(message, state, True)


@router.message(lambda m: m.text and m.text.startswith("/admin_demote"))
async def cmd_admin_demote(message: Message, state: FSMContext):
    await _admin_set_admin(message, state, False)


# --- Generic cancel callback ---


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Действие отменено.", reply_markup=command_keyboard)
    await callback.answer()


_BUTTON_HANDLERS.update(
    {
        "📊 Отчёт": lambda msg, st: cmd_report(msg, st),
        "❓ Помощь": lambda msg, st: cmd_help(msg),
        "⚙️ Настройки": lambda msg, st: cmd_settings(msg, st),
    }
)
