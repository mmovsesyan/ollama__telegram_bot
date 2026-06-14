from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Main menu: clear separation between chat, tools, memory, reminders/tasks.
command_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💬 Чат"), KeyboardButton(text="🔍 Поиск"), KeyboardButton(text="🌤 Погода")],
        [KeyboardButton(text="⏰ Напомнить"), KeyboardButton(text="📋 Задача"), KeyboardButton(text="📝 Заметка")],
        [KeyboardButton(text="📒 Список"), KeyboardButton(text="🧠 Память"), KeyboardButton(text="📊 Отчёт")],
        [KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# FSM keyboard keeps main actions available while showing cancel.
fsm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Поиск"), KeyboardButton(text="⏰ Напомнить"), KeyboardButton(text="📝 Заметка")],
        [KeyboardButton(text="🧠 Память"), KeyboardButton(text="📋 Задача"), KeyboardButton(text="🌤 Погода")],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

base_keyboard = command_keyboard
