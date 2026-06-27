"""Compatibility shim for old `from bot.routers.cron import ...` imports.

The real handlers have moved to domain routers under `bot.routers`. This
module re-exports their public helpers and command/callback functions so
existing tests and late-importing code keep working without modification.
"""
import sys
import types

__all__ = [
    # service helpers
    "_process_remind",
    "_process_task_from_text",
    # common helpers
    "_BUTTON_HANDLERS",
    "_COMMAND_BUTTONS",
    "_classify_memory",
    "_clean_snippet",
    "_extract_main_text",
    "_format_interval",
    "_format_trigger",
    "_fsm_guard",
    "_is_safe_monitor_url",
    "_is_safe_monitor_url_async",
    "_normalize_url",
    "_parse_interval",
    "ollama_web_fetch",
    "ollama_web_search",
    "send_alert",
    "_user_tz",
    # routers
    "router",
    "reminders_router",
    "tasks_router",
    "notes_router",
    "monitors_router",
    "memory_kb_router",
    "news_weather_router",
    "reports_admin_router",
    # reminder handlers
    "cmd_remind",
    "btn_remind",
    "process_remind",
    "cb_remind_quick",
    "process_remind_time",
    "cmd_reminders",
    "cmd_remind_cancel",
    "process_remind_cancel",
    "cb_del_reminder",
    "cb_edit_reminder",
    "cb_edit_reminder_content",
    "cb_edit_reminder_time",
    "process_edit_reminder_content",
    "process_edit_reminder_time",
    "cb_add_reminder",
    "cb_reminder_done",
    # task handlers
    "cmd_task",
    "process_task_text",
    "process_task_time_manual",
    "cb_select_task_time",
    # note handlers
    "cmd_note",
    "cb_note_manual",
    "process_note",
    # monitor handlers
    "cmd_monitor_add",
    "process_monitor_name",
    "process_monitor_url",
    "cb_monitor_interval",
    "process_monitor_interval",
    "_finish_monitor_add",
    "_process_monitor_add",
    "cmd_monitors",
    "cmd_monitor_remove",
    "process_monitor_remove",
    "cb_del_monitor",
    "cb_add_monitor",
    # memory/kb handlers
    "cmd_memory",
    "cmd_memory_add",
    "process_memory_add",
    "cmd_memory_summary",
    "cmd_cleanup",
    "cmd_memory_remove",
    "process_memory_remove",
    "cb_memory_menu",
    "_format_memory_item",
    "_filter_memories",
    "_show_memories",
    "_send_memory_summary",
    "cb_memory_page",
    "cb_memory_filter",
    "cb_del_memory",
    "cb_select_memory_category",
    "cb_add_memory",
    "cmd_kb",
    "btn_kb",
    "process_kb",
    "_process_kb",
    # news/weather/search/fetch handlers
    "_format_search_results",
    "_process_news",
    "_process_digest",
    "cmd_news",
    "process_news",
    "cmd_news_subscribe",
    "cmd_news_unsubscribe",
    "cmd_weather",
    "_process_weather",
    "process_weather",
    "btn_smart_block",
    "cmd_search",
    "_process_search",
    "process_search",
    "cmd_fetch",
    "_process_fetch",
    "process_fetch",
    # reports/admin/misc handlers
    "cmd_report",
    "cmd_help",
    "cb_suggest",
    "cmd_docs",
    "cmd_forget_doc",
    "cmd_images",
    "cmd_forget_image",
    "_admin_required",
    "_format_user_row",
    "cmd_admin_requests",
    "cmd_admin_list",
    "cb_admin_action",
    "_admin_set_status",
    "cmd_admin_approve",
    "cmd_admin_reject",
    "cmd_admin_block",
    "cmd_admin_remove",
    "_admin_set_admin",
    "cmd_admin_promote",
    "cmd_admin_demote",
    "cb_cancel",
]

from aiogram import Router

from bot.routers import (
    memory_kb,
    monitors,
    news_weather,
    notes,
    reminders,
    reports_admin,
    tasks,
)
from bot.routers.common import (
    _BUTTON_HANDLERS,
    _COMMAND_BUTTONS,
    _classify_memory,
    _clean_snippet,
    _extract_main_text,
    _format_interval,
    _format_trigger,
    _fsm_guard,
    _is_safe_monitor_url,
    _is_safe_monitor_url_async,
    _normalize_url,
    _parse_interval,
    ollama_web_fetch,
    ollama_web_search,
    send_alert,
    _user_tz,
)
from bot.services import reminders as reminders_service

# Re-export service helpers.
_process_remind = reminders_service._process_remind
_process_task_from_text = reminders_service._process_task_from_text

# Re-export routers.
reminders_router = reminders.router
tasks_router = tasks.router
notes_router = notes.router
monitors_router = monitors.router
memory_kb_router = memory_kb.router
news_weather_router = news_weather.router
reports_admin_router = reports_admin.router

# Combined router for code that used the old monolithic `cron.router`.
router = Router()
router.include_router(reminders.router)
router.include_router(tasks.router)
router.include_router(notes.router)
router.include_router(monitors.router)
router.include_router(memory_kb.router)
router.include_router(news_weather.router)
router.include_router(reports_admin.router)

# Re-export reminder handlers.
cmd_remind = reminders.cmd_remind
btn_remind = reminders.btn_remind
process_remind = reminders.process_remind
cb_remind_quick = reminders.cb_remind_quick
process_remind_time = reminders.process_remind_time
cmd_reminders = reminders.cmd_reminders
cmd_remind_cancel = reminders.cmd_remind_cancel
process_remind_cancel = reminders.process_remind_cancel
cb_del_reminder = reminders.cb_del_reminder
cb_edit_reminder = reminders.cb_edit_reminder
cb_edit_reminder_content = reminders.cb_edit_reminder_content
cb_edit_reminder_time = reminders.cb_edit_reminder_time
process_edit_reminder_content = reminders.process_edit_reminder_content
process_edit_reminder_time = reminders.process_edit_reminder_time
cb_add_reminder = reminders.cb_add_reminder
cb_reminder_done = reminders.cb_reminder_done

# Re-export task handlers.
cmd_task = tasks.cmd_task
process_task_text = tasks.process_task_text
process_task_time_manual = tasks.process_task_time_manual
cb_select_task_time = tasks.cb_select_task_time

# Re-export note handlers.
cmd_note = notes.cmd_note
cb_note_manual = notes.cb_note_manual
process_note = notes.process_note

# Re-export monitor handlers.
cmd_monitor_add = monitors.cmd_monitor_add
process_monitor_name = monitors.process_monitor_name
process_monitor_url = monitors.process_monitor_url
cb_monitor_interval = monitors.cb_monitor_interval
process_monitor_interval = monitors.process_monitor_interval
_finish_monitor_add = monitors._finish_monitor_add
_process_monitor_add = monitors._process_monitor_add
cmd_monitors = monitors.cmd_monitors
cmd_monitor_remove = monitors.cmd_monitor_remove
process_monitor_remove = monitors.process_monitor_remove
cb_del_monitor = monitors.cb_del_monitor
cb_add_monitor = monitors.cb_add_monitor

# Re-export memory/kb handlers.
cmd_memory = memory_kb.cmd_memory
cmd_memory_add = memory_kb.cmd_memory_add
process_memory_add = memory_kb.process_memory_add
cmd_memory_summary = memory_kb.cmd_memory_summary
cmd_cleanup = memory_kb.cmd_cleanup
cmd_memory_remove = memory_kb.cmd_memory_remove
process_memory_remove = memory_kb.process_memory_remove
cb_memory_menu = memory_kb.cb_memory_menu
_format_memory_item = memory_kb._format_memory_item
_filter_memories = memory_kb._filter_memories
_show_memories = memory_kb._show_memories
_send_memory_summary = memory_kb._send_memory_summary
cb_memory_page = memory_kb.cb_memory_page
cb_memory_filter = memory_kb.cb_memory_filter
cb_del_memory = memory_kb.cb_del_memory
cb_select_memory_category = memory_kb.cb_select_memory_category
cb_add_memory = memory_kb.cb_add_memory
cmd_kb = memory_kb.cmd_kb
btn_kb = memory_kb.btn_kb
process_kb = memory_kb.process_kb
_process_kb = memory_kb._process_kb

# Re-export news/weather/search/fetch handlers.
_format_search_results = news_weather._format_search_results
_process_news = news_weather._process_news
_process_digest = news_weather._process_digest
cmd_news = news_weather.cmd_news
process_news = news_weather.process_news
cmd_news_subscribe = news_weather.cmd_news_subscribe
cmd_news_unsubscribe = news_weather.cmd_news_unsubscribe
cmd_weather = news_weather.cmd_weather
_process_weather = news_weather._process_weather
process_weather = news_weather.process_weather
btn_smart_block = news_weather.btn_smart_block
cmd_search = news_weather.cmd_search
_process_search = news_weather._process_search
process_search = news_weather.process_search
cmd_fetch = news_weather.cmd_fetch
_process_fetch = news_weather._process_fetch
process_fetch = news_weather.process_fetch

# Re-export reports/admin/misc handlers.
cmd_report = reports_admin.cmd_report
cmd_help = reports_admin.cmd_help
cb_suggest = reports_admin.cb_suggest
cmd_docs = reports_admin.cmd_docs
cmd_forget_doc = reports_admin.cmd_forget_doc
cmd_images = reports_admin.cmd_images
cmd_forget_image = reports_admin.cmd_forget_image
_admin_required = reports_admin._admin_required
_format_user_row = reports_admin._format_user_row
cmd_admin_requests = reports_admin.cmd_admin_requests
cmd_admin_list = reports_admin.cmd_admin_list
cb_admin_action = reports_admin.cb_admin_action
_admin_set_status = reports_admin._admin_set_status
cmd_admin_approve = reports_admin.cmd_admin_approve
cmd_admin_reject = reports_admin.cmd_admin_reject
cmd_admin_block = reports_admin.cmd_admin_block
cmd_admin_remove = reports_admin.cmd_admin_remove
_admin_set_admin = reports_admin._admin_set_admin
cmd_admin_promote = reports_admin.cmd_admin_promote
cmd_admin_demote = reports_admin.cmd_admin_demote
cb_cancel = reports_admin.cb_cancel

# Modules whose `db` should stay in sync when tests/code set `cron.db`.
_db_modules = [reminders, tasks, notes, monitors, memory_kb, news_weather, reports_admin]


class _CronModule(types.ModuleType):
    """Proxy module so that `cron.db = db` injects db into every domain router."""

    @property
    def db(self):
        return _db_modules[0].db if _db_modules else None

    @db.setter
    def db(self, value):
        for mod in _db_modules:
            mod.db = value


# Replace the plain module object with the proxy while preserving its attributes.
_current = sys.modules[__name__]
_cron_module = _CronModule(__name__)
_cron_module.__dict__.update(_current.__dict__)
_cron_module.__file__ = __file__
_cron_module.__doc__ = __doc__
sys.modules[__name__] = _cron_module
