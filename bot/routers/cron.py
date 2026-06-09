from aiogram import Router
from aiogram.types import Message
import re
from datetime import datetime, timedelta

router = Router()

db = None  # injected in __init__

async def send_alert(user_id: int, text: str):
    from bot.bot import bot as aiogram_bot
    try:
        await aiogram_bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        print(f"[ALERT] Failed to send to {user_id}: {e}")

def parse_time(text: str) -> datetime:
    now = datetime.now()
    text = text.lower().strip()

    if text.startswith("через"):
        match = re.search(r'\d+', text)
        if match:
            num = int(match.group())
            if "минут" in text:
                return now + timedelta(minutes=num)
            if "час" in text:
                return now + timedelta(hours=num)
            if "день" in text or "дн" in text:
                return now + timedelta(days=num)

    if "завтра" in text:
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(hour=h, minute=m, second=0, microsecond=0)

    try:
        return datetime.fromisoformat(text)
    except:
        pass

    return now + timedelta(minutes=5)

@router.message(lambda m: m.text and m.text.startswith("/remind"))
async def cmd_remind(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Использование: /remind <время> <текст>\n"
            "Примеры:\n"
            "/remind через 5 минут позвонить брокеру\n"
            "/remind завтра в 9:00 проверить отчет\n"
            "/remind 2026-06-10 14:00 встреча"
        )
        return

    text = parts[1]
    time_patterns = [
        r"^(через \d+ (?:минут|час|день|дней|дня))",
        r"^(завтра в \d{1,2}:\d{2})",
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
        r"^(\d{2}:\d{2})",
    ]

    trigger_at = None
    content = text

    for pattern in time_patterns:
        match = re.match(pattern, text)
        if match:
            time_str = match.group(1)
            content = text[len(time_str):].strip()
            trigger_at = parse_time(time_str)
            break

    if not trigger_at:
        trigger_at = datetime.now() + timedelta(hours=1)

    reminder_id = db.add_reminder(
        user_id=message.from_user.id,
        content=content,
        trigger_at=trigger_at.isoformat()
    )

    await message.answer(
        f"⏰ Напоминание #{reminder_id} установлено на {trigger_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"Текст: {content}"
    )

@router.message(lambda m: m.text and m.text == "/reminders")
async def cmd_reminders(message: Message):
    if message.from_user is None:
        return

    reminders = db.get_user_reminders(message.from_user.id)
    if not reminders:
        await message.answer("Нет активных напоминаний.")
        return

    text = "Активные напоминания:\n"
    for r in reminders:
        time_str = r.get('trigger_at', 'ASAP')
        text += f"#{r['id']} | {time_str} | {r['content']}\n"

    await message.answer(text)

@router.message(lambda m: m.text and m.text.startswith("/remind_cancel"))
async def cmd_remind_cancel(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /remind_cancel <id>")
        return

    try:
        rid = int(parts[1])
        db.disable_reminder(rid)
        await message.answer(f"Напоминание #{rid} отменено.")
    except ValueError:
        await message.answer("Укажите числовой ID напоминания.")

@router.message(lambda m: m.text and m.text.startswith("/note"))
async def cmd_note(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        notes = db.get_notes(message.from_user.id)
        if notes:
            await message.answer(f"Твои заметки:\n{notes}")
        else:
            await message.answer("Нет сохранённых заметок. Используй /note <текст>")
        return

    db.add_note(message.from_user.id, parts[1])
    await message.answer("Заметка сохранена. AI будет помнить это.")

@router.message(lambda m: m.text and m.text.startswith("/monitor_add"))
async def cmd_monitor_add(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            "Использование: /monitor_add <name> <url> [interval_seconds]\n"
            "Пример: /monitor_add Google https://google.com 60"
        )
        return

    name = parts[1]
    url = parts[2]
    interval = 300
    if len(parts) >= 4:
        try:
            interval = int(parts[3])
        except:
            pass

    mid = db.add_monitor(
        user_id=message.from_user.id,
        name=name,
        url=url,
        interval=interval
    )
    await message.answer(f"Монитор #{mid} добавлен: {name} -> {url} (каждые {interval} сек)")

@router.message(lambda m: m.text and m.text == "/monitors")
async def cmd_monitors(message: Message):
    if message.from_user is None:
        return

    monitors = db.get_monitors(message.from_user.id)
    if not monitors:
        await message.answer("Нет активных мониторов.")
        return

    text = "Активные мониторы:\n"
    for m in monitors:
        status = f"HTTP {m['last_status']}" if m['last_status'] else "не проверялся"
        text += f"#{m['id']} | {m['name']} | {status} | {m['url']}\n"

    await message.answer(text)

@router.message(lambda m: m.text and m.text.startswith("/monitor_remove"))
async def cmd_monitor_remove(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /monitor_remove <id>")
        return

    try:
        mid = int(parts[1])
        db.remove_monitor(mid)
        await message.answer(f"Монитор #{mid} удалён.")
    except ValueError:
        await message.answer("Укажите числовой ID.")

@router.message(lambda m: m.text and m.text.startswith("/report"))
async def cmd_report(message: Message):
    if message.from_user is None:
        return

    now = datetime.now()
    text = f"📊 Ежедневный отчёт ({now.strftime('%Y-%m-%d %H:%M')})\n\n"

    reminders = db.get_user_reminders(message.from_user.id)
    text += f"Напоминаний: {len(reminders)}\n"

    monitors = db.get_monitors(message.from_user.id)
    text += f"Мониторов: {len(monitors)}\n"

    notes = db.get_notes(message.from_user.id)
    if notes:
        text += f"\nЗаметки:\n{notes}"

    memories = db.get_memories(message.from_user.id)
    if memories:
        text += f"\nПамять: {len(memories)} фактов"

    await message.answer(text)


@router.message(lambda m: m.text and m.text.startswith("/memory_add"))
async def cmd_memory_add(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(
            "Использование: /memory_add [<category>] <content>\n"
            "Категории: fact, preference, task, decision\n"
            "Пример: /memory_add preference люблю кофе\n"
            "Пример: /memory_add купить акции TSLA"
        )
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


@router.message(lambda m: m.text and m.text == "/memory")
async def cmd_memory(message: Message):
    if message.from_user is None:
        return

    memories = db.get_memories(message.from_user.id)
    if not memories:
        await message.answer(
            "Нет сохранённых фактов.\n"
            "Используй /memory_add <категория> <текст>"
        )
        return

    text = "🧠 Память:\n"
    for m in memories:
        cat = m.get('category', 'fact')
        content = m.get('content', '')
        text += f"#{m['id']} | [{cat}] {content}\n"

    await message.answer(text)


@router.message(lambda m: m.text and m.text.startswith("/memory_remove"))
async def cmd_memory_remove(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /memory_remove <id>")
        return

    try:
        mid = int(parts[1])
        db.remove_memory(mid)
        await message.answer(f"Факт #{mid} удалён.")
    except ValueError:
        await message.answer("Укажите числовой ID.")
