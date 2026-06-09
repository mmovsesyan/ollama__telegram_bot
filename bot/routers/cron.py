from aiogram import Router
from aiogram.types import Message
import re
from datetime import datetime, timedelta

import aiohttp

router = Router()

db = None  # injected in __init__


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
                if resp.status == 200:
                    data = await resp.json()
                    return data, None
                else:
                    text = await resp.text()
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
                if resp.status == 200:
                    data = await resp.json()
                    return data, None
                else:
                    text = await resp.text()
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


@router.message(lambda m: m.text and m.text.startswith("/remind_remove"))
async def cmd_remind_remove(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /remind_remove <id>")
        return

    try:
        rid = int(parts[1])
        db.disable_reminder(rid)
        await message.answer(f"Напоминание #{rid} удалено.")
    except ValueError:
        await message.answer("Укажите числовой ID.")


@router.message(lambda m: m.text and m.text.startswith("/weather"))
async def cmd_weather(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /weather <город>\nПример: /weather Moscow")
        return

    city = parts[1].strip()
    query = f"погода в {city} сейчас"
    await message.answer(f"🌤 Ищу погоду: {city}...")

    result, error = await ollama_web_search(query, max_results=3)
    if error:
        await message.answer(f"❌ {error}")
        return

    items = result.get("results", [])
    if not items:
        await message.answer("Не удалось найти погоду.")
        return

    text = f"🌤 Погода в {city}:\n\n"
    for i, item in enumerate(items[:3], 1):
        title = item.get("title", "")
        content = item.get("content", "")[:800]
        url = item.get("url", "")
        if content:
            text += f"{content}\n"
        if url:
            text += f"{url}\n"
        text += "\n"

    await message.answer(text[:4096])


@router.message(lambda m: m.text and m.text == "/news")
async def cmd_news(message: Message):
    if message.from_user is None:
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
        content = item.get("content", "")[:400]
        text += f"{i}. {title}\n"
        if content:
            text += f"   {content}\n"
        if url:
            text += f"   {url}\n"
        text += "\n"

    await message.answer(text[:4096])


@router.message(lambda m: m.text and m.text.startswith("/search"))
async def cmd_search(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Использование: /search <запрос>\n"
            "Пример: /search последние новости о Tesla\n\n"
            "Требуется OLLAMA_WEB_API_KEY в .env (получить на https://ollama.com)"
        )
        return

    query = parts[1].strip()
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

    text = f"🔍 Результаты поиска: {query}\n\n"
    for i, item in enumerate(items[:5], 1):
        title = item.get("title", "Без названия")
        url = item.get("url", "")
        content = item.get("content", "")[:500]
        text += f"{i}. {title}\n"
        if url:
            text += f"   {url}\n"
        if content:
            text += f"   {content}\n"
        text += "\n"

    await message.answer(text[:4096])


@router.message(lambda m: m.text and m.text.startswith("/fetch"))
async def cmd_fetch(message: Message):
    if message.from_user is None:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Использование: /fetch <url>\n"
            "Пример: /fetch https://example.com/article\n\n"
            "Требуется OLLAMA_WEB_API_KEY в .env"
        )
        return

    url = parts[1].strip()
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
