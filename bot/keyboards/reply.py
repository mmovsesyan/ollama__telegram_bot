from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

command_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🤖 Модели"), KeyboardButton(text="🔍 Поиск")],
        [KeyboardButton(text="🌤 Погода"), KeyboardButton(text="📰 Новости")],
        [KeyboardButton(text="🧠 Память"), KeyboardButton(text="📝 Заметка")],
        [KeyboardButton(text="⏰ Напоминание"), KeyboardButton(text="🔍 Мониторы")],
        [KeyboardButton(text="➕ Монитор"), KeyboardButton(text="📊 Отчёт")],
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

# Combined keyboard for FSM states: keeps main commands + cancel button
fsm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🤖 Модели"), KeyboardButton(text="🔍 Поиск")],
        [KeyboardButton(text="🌤 Погода"), KeyboardButton(text="📰 Новости")],
        [KeyboardButton(text="🧠 Память"), KeyboardButton(text="📝 Заметка")],
        [KeyboardButton(text="⏰ Напоминание"), KeyboardButton(text="🔍 Мониторы")],
        [KeyboardButton(text="➕ Монитор"), KeyboardButton(text="📊 Отчёт")],
        [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="🗑 Очистить")],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)
base_keyboard = command_keyboard
