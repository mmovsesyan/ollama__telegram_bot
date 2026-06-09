from bot.ollama.api import validate_installation_with_configuration
from bot.settings import OLLAMA_MODEL, DB_PATH
from bot.db import Database

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from aiogram.types import BotCommand
import aiohttp
from datetime import datetime

COMMANDS = [
    BotCommand(command="start", description="Приветствие и настройка"),
    BotCommand(command="models", description="Список моделей"),
    BotCommand(command="model", description="Сменить модель"),
    BotCommand(command="clear", description="Очистить историю"),
    BotCommand(command="note", description="Сохранить заметку"),
    BotCommand(command="memory", description="Показать память"),
    BotCommand(command="memory_add", description="Добавить факт в память"),
    BotCommand(command="memory_remove", description="Удалить факт"),
    BotCommand(command="remind", description="Добавить напоминание"),
    BotCommand(command="reminders", description="Список напоминаний"),
    BotCommand(command="remind_cancel", description="Отменить напоминание"),
    BotCommand(command="monitor_add", description="Добавить монитор"),
    BotCommand(command="monitors", description="Список мониторов"),
    BotCommand(command="monitor_remove", description="Удалить монитор"),
    BotCommand(command="search", description="Поиск в интернете"),
    BotCommand(command="fetch", description="Загрузить страницу"),
    BotCommand(command="weather", description="Погода в городе"),
    BotCommand(command="news", description="Актуальные новости"),
    BotCommand(command="report", description="Ежедневный отчет"),
    BotCommand(command="help", description="Полная справка"),
]


async def main() -> None:
    # Pre validate required model and overall ollama health.
    await validate_installation_with_configuration(OLLAMA_MODEL)

    from bot.bot import bot as aiogram_bot
    from bot.bot import dp
    from bot.routers import start, completion, cron

    # Set Telegram menu commands
    try:
        await aiogram_bot.set_my_commands(COMMANDS)
        print("[BOT] Menu commands registered")
    except Exception as e:
        print(f"[BOT] Failed to set commands: {e}")

    # Init database
    db = Database(DB_PATH)

    # Inject db into routers
    completion.db = db
    cron.db = db

    # Order matters: cron commands must be checked before generic completion handler
    dp.include_routers(start.router, cron.router, completion.router)

    # Setup scheduler
    scheduler = AsyncIOScheduler()

    async def check_reminders():
        now = datetime.now().isoformat()
        reminders = db.get_pending_reminders(now)
        for r in reminders:
            try:
                await aiogram_bot.send_message(
                    chat_id=r['user_id'],
                    text=f"⏰ Напоминание #{r['id']}:\n{r['content']}"
                )
                db.disable_reminder(r['id'])
            except Exception as e:
                print(f"[CRON] Failed to send reminder {r['id']}: {e}")

    async def check_monitors():
        monitors = db.get_all_active_monitors()
        async with aiohttp.ClientSession() as session:
            for m in monitors:
                try:
                    async with session.request(
                        method=m.get('method', 'GET'),
                        url=m['url'],
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        status = response.status
                        db.update_monitor_status(m['id'], status)
                        if status != m.get('expected_status', 200):
                            try:
                                await aiogram_bot.send_message(
                                    chat_id=m['user_id'],
                                    text=f"🚨 ALERT #{m['id']}: {m['name']}\n"
                                         f"URL: {m['url']}\n"
                                         f"Expected HTTP {m.get('expected_status', 200)}, got HTTP {status}"
                                )
                            except Exception as send_err:
                                print(f"[CRON] Failed alert: {send_err}")
                except Exception as e:
                    db.update_monitor_status(m['id'], 0)
                    try:
                        await aiogram_bot.send_message(
                            chat_id=m['user_id'],
                            text=f"🚨 ALERT #{m['id']}: {m['name']}\n"
                                 f"URL: {m['url']}\n"
                                 f"Error: {str(e)[:200]}"
                        )
                    except Exception as send_err:
                        print(f"[CRON] Failed alert: {send_err}")

    scheduler.add_job(check_reminders, IntervalTrigger(seconds=30), id="reminders", replace_existing=True)
    scheduler.add_job(check_monitors, IntervalTrigger(seconds=60), id="monitors", replace_existing=True)
    scheduler.start()

    print(f"[OLLAMA] Selected base model -> {OLLAMA_MODEL}")
    print("[BOT] Start polling...")
    await dp.start_polling(aiogram_bot)
