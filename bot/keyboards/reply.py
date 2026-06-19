from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Main menu: clear separation between tools, memory, reminders/tasks.
# Free-form chat doesn't need a button — users just type. Removing it
# frees a slot for actually useful actions.
command_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✨ Умный запрос"), KeyboardButton(text="⏰ Напомнить")],
        [KeyboardButton(text="📒 Список"), KeyboardButton(text="🧠 Память"), KeyboardButton(text="📚 База")],
        [KeyboardButton(text="📊 Отчёт"), KeyboardButton(text="❓ Помощь"), KeyboardButton(text="⚙️ Настройки")],
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
        [KeyboardButton(text="✨ Умный запрос"), KeyboardButton(text="⏰ Напомнить")],
        [KeyboardButton(text="🧠 Память"), KeyboardButton(text="📚 База"), KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

base_keyboard = command_keyboard
