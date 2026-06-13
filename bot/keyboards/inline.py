from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

answer_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="👍", callback_data="like"),
            InlineKeyboardButton(text="👎", callback_data="dislike"),
        ],
    ]
)


def confirm_keyboard(confirm_data: str, cancel_data: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=confirm_data),
                InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_data),
            ],
        ]
    )


def memory_category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📌 Факт", callback_data="mem_cat:fact"),
                InlineKeyboardButton(text="❤️ Предпочтение", callback_data="mem_cat:preference"),
            ],
            [
                InlineKeyboardButton(text="📋 Задача", callback_data="mem_cat:task"),
                InlineKeyboardButton(text="⚖️ Решение", callback_data="mem_cat:decision"),
            ],
            [InlineKeyboardButton(text="🤖 Авто", callback_data="mem_cat:auto")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def reminder_quick_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏰ Через 5 минут", callback_data="remind_quick:5m")],
            [InlineKeyboardButton(text="📅 Завтра в 9:00", callback_data="remind_quick:tomorrow9")],
            [InlineKeyboardButton(text="🔁 Каждый день в 9:00", callback_data="remind_quick:daily9")],
            [InlineKeyboardButton(text="🤖 AI выберет время", callback_data="remind_quick:auto")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def recurring_suggest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Каждый день", callback_data="recur:daily")],
            [InlineKeyboardButton(text="🔁 По будням", callback_data="recur:weekday")],
            [InlineKeyboardButton(text="🔁 Выходные", callback_data="recur:weekend")],
            [InlineKeyboardButton(text="⏰ Только раз", callback_data="recur:once")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )
