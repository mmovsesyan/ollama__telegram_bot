from aiogram.fsm.state import State, StatesGroup


class BotStates(StatesGroup):
    waiting_model = State()
    waiting_note = State()
    waiting_memory_add = State()
    waiting_memory_remove = State()
    waiting_remind = State()
    waiting_remind_time = State()
    waiting_remind_cancel = State()
    waiting_remind_remove = State()
    waiting_task_text = State()
    waiting_task_time = State()
    waiting_monitor_add = State()
    waiting_monitor_name = State()
    waiting_monitor_url = State()
    waiting_monitor_interval = State()
    waiting_monitor_remove = State()
    waiting_weather = State()
    waiting_search = State()
    waiting_fetch = State()
