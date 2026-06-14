from bot.ollama.api import validate_installation_with_configuration
from bot.settings import OLLAMA_MODEL, DB_PATH
from bot.ollama import generate_chat_completion, OllamaChat, OllamaChatMessage
from bot.ollama.dto import OllamaErrorChunk
from bot.tasks_exec import execute_smart
from bot.db import Database

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
import aiohttp
from datetime import datetime, timezone

COMMANDS = [
    BotCommand(command="start", description="Приветствие и меню"),
    BotCommand(command="help", description="Примеры и команды"),
    BotCommand(command="remind", description="Добавить напоминание"),
    BotCommand(command="task", description="Задача (AI выполнит)"),
    BotCommand(command="reminders", description="Список напоминаний"),
    BotCommand(command="memory", description="Показать память"),
    BotCommand(command="memory_add", description="Добавить факт в память"),
    BotCommand(command="note", description="Сохранить заметку"),
    BotCommand(command="search", description="Поиск в интернете"),
    BotCommand(command="weather", description="Погода в городе"),
    BotCommand(command="news", description="Актуальные новости"),
    BotCommand(command="monitor_add", description="Добавить монитор сайта"),
    BotCommand(command="monitors", description="Список мониторов"),
    BotCommand(command="models", description="Список моделей"),
    BotCommand(command="model", description="Сменить модель"),
    BotCommand(command="clear", description="Очистить историю"),
    BotCommand(command="report", description="Ежедневный отчет"),
]


async def main() -> None:
    # Pre validate required model and overall ollama health.
    await validate_installation_with_configuration(OLLAMA_MODEL)

    from bot.bot import bot as aiogram_bot
    from bot.bot import dp
    from bot.routers import start, completion, cron
    from bot.handlers import smart as smart_handler

    # Set Telegram menu commands
    try:
        await aiogram_bot.set_my_commands(COMMANDS, scope=BotCommandScopeAllPrivateChats())
        print("[BOT] Menu commands registered")
    except Exception as e:
        print(f"[BOT] Failed to set commands: {e}")

    # Init database
    db = Database(DB_PATH)

    # Inject db into routers and services
    completion.db = db
    cron.db = db
    from bot.services import reminders as reminders_service
    reminders_service.db = db

    # Order matters: explicit cron commands and FSM states must be checked before the
    # smart free-form text handler. Smart handler replaces the legacy catch-all completion router.
    dp.include_routers(start.router, cron.router, smart_handler.router, completion.router)

    # Setup scheduler
    scheduler = AsyncIOScheduler()

    def _next_trigger(trigger_at: str, recurring: str | None) -> str | None:
        from datetime import timedelta
        try:
            dt = datetime.fromisoformat(trigger_at)
        except Exception:
            return None
        if not recurring:
            return None
        if recurring == "daily":
            return (dt + timedelta(days=1)).isoformat()
        if recurring == "weekday":
            nxt = dt + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
            return nxt.isoformat()
        if recurring == "weekend":
            nxt = dt + timedelta(days=1)
            while nxt.weekday() < 5:
                nxt += timedelta(days=1)
            return nxt.isoformat()
        if recurring == "weekly":
            return (dt + timedelta(weeks=1)).isoformat()
        if recurring in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
            weekday_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
            target = weekday_map[recurring]
            nxt = dt + timedelta(days=1)
            while nxt.weekday() != target:
                nxt += timedelta(days=1)
            return nxt.isoformat()
        return None

    async def check_reminders():
        now = datetime.now(timezone.utc).isoformat()
        reminders = db.get_pending_reminders(now)
        for r in reminders:
            try:
                action = r.get('action', 'notify')
                user_id = r['user_id']
                content = r['content']

                if action == 'execute':
                    # Try smart execution (real APIs) first
                    smart_result = await execute_smart(content)
                    if smart_result is not None:
                        await aiogram_bot.send_message(
                            chat_id=user_id,
                            text=f"⏰ Задача #{r['id']}: {content}\n\n{smart_result[:3800]}",
                        )
                    else:
                        # Fallback to generic LLM
                        messages = [
                            OllamaChatMessage(role="system", content="Ты ассистент. Выполни запрос пользователя кратко, полезно и по делу."),
                            OllamaChatMessage(role="user", content=content),
                        ]
                        response = ""
                        async for is_done, chunk in generate_chat_completion(messages, model=OLLAMA_MODEL):
                            if is_done:
                                break
                            if isinstance(chunk, OllamaErrorChunk):
                                response = f"[Ошибка Ollama: {chunk.error}]"
                                break
                            response += chunk.message.content
                        if not response.strip():
                            response = "(пустой ответ от модели)"
                        await aiogram_bot.send_message(
                            chat_id=user_id,
                            text=f"⏰ Задача #{r['id']}: {content}\n\n{response[:3800]}",
                        )
                else:
                    await aiogram_bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ Напоминание #{r['id']}:\n{content}"
                    )

                recurring = r.get('recurring')
                nxt = _next_trigger(r['trigger_at'], recurring)
                if nxt and recurring:
                    db.reschedule_reminder(r['id'], nxt)
                else:
                    db.disable_reminder(r['id'])
            except Exception as e:
                print(f"[CRON] Failed to send reminder {r['id']}: {e}")

    _monitor_alerted: dict[int, bool] = {}

    async def check_monitors():
        now = datetime.now(timezone.utc)
        monitors = db.get_all_active_monitors()
        active_ids = {m['id'] for m in monitors}
        # Clean up orphaned alerts for removed monitors
        for mid in list(_monitor_alerted.keys()):
            if mid not in active_ids:
                del _monitor_alerted[mid]

        async with aiohttp.ClientSession() as session:
            for m in monitors:
                interval = m.get('check_interval', 300)
                last_check_str = m.get('last_check')
                if last_check_str:
                    try:
                        last_check = datetime.fromisoformat(str(last_check_str).replace(' ', 'T'))
                        if (now - last_check).total_seconds() < interval:
                            continue
                    except Exception:
                        pass
                expected = m.get('expected_status', 200)
                mid = m['id']
                try:
                    async with session.request(
                        method=m.get('method', 'GET'),
                        url=m['url'],
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        status = response.status
                        db.update_monitor_status(mid, status)
                        if status != expected:
                            if not _monitor_alerted.get(mid):
                                _monitor_alerted[mid] = True
                                try:
                                    await aiogram_bot.send_message(
                                        chat_id=m['user_id'],
                                        text=f"🚨 ALERT #{mid}: {m['name']}\n"
                                             f"URL: {m['url']}\n"
                                             f"Expected HTTP {expected}, got HTTP {status}"
                                    )
                                except Exception as send_err:
                                    print(f"[CRON] Failed alert: {send_err}")
                        else:
                            if _monitor_alerted.pop(mid, None):
                                try:
                                    await aiogram_bot.send_message(
                                        chat_id=m['user_id'],
                                        text=f"✅ RECOVERY #{mid}: {m['name']}\n"
                                             f"URL: {m['url']}\n"
                                             f"HTTP {status} — сайт снова доступен"
                                    )
                                except Exception as send_err:
                                    print(f"[CRON] Failed recovery: {send_err}")
                except Exception as e:
                    db.update_monitor_status(mid, 0)
                    if not _monitor_alerted.get(mid):
                        _monitor_alerted[mid] = True
                        try:
                            await aiogram_bot.send_message(
                                chat_id=m['user_id'],
                                text=f"🚨 ALERT #{mid}: {m['name']}\n"
                                     f"URL: {m['url']}\n"
                                     f"Error: {str(e)[:200]}"
                            )
                        except Exception as send_err:
                            print(f"[CRON] Failed alert: {send_err}")

    async def cleanup_sessions():
        from bot.routers import completion
        await completion._cleanup_old_chats()

    scheduler.add_job(check_reminders, IntervalTrigger(seconds=30), id="reminders", replace_existing=True)
    scheduler.add_job(check_monitors, IntervalTrigger(seconds=60), id="monitors", replace_existing=True)
    scheduler.add_job(cleanup_sessions, IntervalTrigger(minutes=30), id="cleanup", replace_existing=True)
    scheduler.start()

    print(f"[OLLAMA] Selected base model -> {OLLAMA_MODEL}")
    print("[BOT] Start polling...")
    await dp.start_polling(aiogram_bot)
