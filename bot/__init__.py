from bot.ollama.api import validate_installation_with_configuration
from bot.settings import OLLAMA_MODEL, DB_PATH
from bot.ollama import generate_chat_completion, OllamaChatMessage
from bot.ollama.dto import OllamaErrorChunk
from bot.tasks_exec import execute_smart
from bot.db import Database

import asyncio
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
    BotCommand(command="settings", description="Настройки бота"),
    BotCommand(command="briefing", description="Утренний брифинг сейчас"),
]


async def main() -> None:
    # Pre validate required model and overall ollama health.
    await validate_installation_with_configuration(OLLAMA_MODEL)

    from bot.bot import bot as aiogram_bot
    from bot.bot import dp
    from bot.routers import start, completion, cron, settings
    from bot.handlers import smart as smart_handler
    from bot.handlers import voice as voice_handler

    # Set Telegram menu commands
    try:
        await aiogram_bot.set_my_commands(COMMANDS, scope=BotCommandScopeAllPrivateChats())
        print("[BOT] Menu commands registered")
    except Exception as e:
        print(f"[BOT] Failed to set commands: {e}")

    # Init database
    db = Database(DB_PATH)

    # Inject db into routers and services BEFORE wiring them up. If we
    # registered the routers first, an early Telegram update could land
    # while db is still None and crash with AttributeError.
    completion.db = db
    cron.db = db
    smart_handler.db = db
    voice_handler.db = db
    start.db = db
    settings.db = db
    from bot.intent.context import ContextBuilder
    ContextBuilder.db = db
    from bot.services import reminders as reminders_service
    from bot.services import kb as kb_service
    from bot.services import rss_news as rss_news_service
    from bot.services import briefing as briefing_service
    from bot.services import voice as voice_service
    from bot.services import news_categories as news_categories_service
    reminders_service.db = db
    kb_service.db = db
    rss_news_service.db = db
    briefing_service.db = db
    voice_service.db = db
    news_categories_service.db = db

    # Order matters: explicit cron commands and FSM states must be checked
    # before the smart free-form text handler. completion.router goes BEFORE
    # smart so its button matchers (F.text == "❓ Помощь" etc.) win — smart
    # is the catch-all for everything else.
    dp.include_routers(start.router, settings.router, cron.router, completion.router, voice_handler.router, smart_handler.router)

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
        if recurring == "monthly":
            return (dt + timedelta(days=30)).isoformat()
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
        # Telegram rate-limits at ~30 msg/sec; if many reminders fire in one
        # tick (especially after downtime), space them out so we don't
        # silently drop the tail under HTTP 429.
        SEND_DELAY = 0.05  # ~20 messages/second, safe headroom
        sent_count = 0
        for r in reminders:
            try:
                action = r.get('action', 'notify')
                user_id = r['user_id']
                content = r['content']

                if sent_count > 0:
                    await asyncio.sleep(SEND_DELAY)

                if action == 'execute':
                    # Try smart execution (real APIs) first
                    smart_result = await execute_smart(content)
                    if smart_result is not None:
                        await aiogram_bot.send_message(
                            chat_id=user_id,
                            text=f"⏰ Задача: {content}\n\n{smart_result[:3800]}",
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
                            text=f"⏰ Задача: {content}\n\n{response[:3800]}",
                        )
                else:
                    await aiogram_bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ Напоминание:\n{content}"
                    )

                recurring = r.get('recurring')
                nxt = _next_trigger(r['trigger_at'], recurring)
                if nxt and recurring:
                    db.reschedule_reminder(r['id'], nxt)
                else:
                    db.disable_reminder(r['id'])
                sent_count += 1
            except Exception as e:
                print(f"[CRON] Failed to send reminder {r['id']}: {e}")

    async def check_monitors():
        now = datetime.now(timezone.utc)
        monitors = db.get_all_active_monitors()

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
                was_alerted = bool(m.get('alerted'))
                try:
                    async with session.request(
                        method=m.get('method', 'GET'),
                        url=m['url'],
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        status = response.status
                        db.update_monitor_status(mid, status)
                        if status != expected:
                            if not was_alerted:
                                db.set_monitor_alerted(mid, True)
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
                            if was_alerted:
                                db.set_monitor_alerted(mid, False)
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
                    if not was_alerted:
                        db.set_monitor_alerted(mid, True)
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

    async def check_briefings():
        if db is None:
            return
        from bot.services import briefing as briefing_service
        from bot.services.profile import now_in_tz
        users = db.get_briefing_enabled_users()
        for prefs in users:
            tz_name = prefs.get("timezone") or "UTC"
            local_now = now_in_tz(tz_name)
            current_time = local_now.strftime("%H:%M")
            if current_time != (prefs.get("briefing_time") or "08:00"):
                continue
            today_str = local_now.strftime("%Y-%m-%d")
            if prefs.get("last_briefing_date") == today_str:
                continue
            await briefing_service.send_briefing(prefs["user_id"], aiogram_bot)
            db.update_briefing_sent(prefs["user_id"], today_str)

    scheduler.add_job(check_reminders, IntervalTrigger(seconds=30), id="reminders", replace_existing=True)
    scheduler.add_job(check_monitors, IntervalTrigger(seconds=60), id="monitors", replace_existing=True)
    scheduler.add_job(cleanup_sessions, IntervalTrigger(minutes=30), id="cleanup", replace_existing=True)
    scheduler.add_job(check_briefings, IntervalTrigger(minutes=1), id="briefing", replace_existing=True)
    scheduler.start()

    print(f"[OLLAMA] Selected base model -> {OLLAMA_MODEL}")
    print("[BOT] Start polling...")
    await dp.start_polling(aiogram_bot)
