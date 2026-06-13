from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Simplified main menu: only the most common entry points.
command_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💬 Чат"), KeyboardButton(text="🔍 Поиск")],
        [KeyboardButton(text="⏰ Напоминание"), KeyboardButton(text="🧠 Память")],
        [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="🗑 Очистить")],
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
        [KeyboardButton(text="🔍 Поиск"), KeyboardButton(text="⏰ Напоминание"), KeyboardButton(text="🧠 Память")],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

base_keyboard = command_keyboard
