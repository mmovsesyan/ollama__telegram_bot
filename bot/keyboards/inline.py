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


def memory_menu_keyboard() -> InlineKeyboardMarkup:
    """Main memory menu: add vs view."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить факт", callback_data="memory_menu:add_fact")],
            [InlineKeyboardButton(text="➕ Добавить предпочтение", callback_data="memory_menu:add_preference")],
            [InlineKeyboardButton(text="➕ Добавить заметку", callback_data="memory_menu:add_note")],
            [InlineKeyboardButton(text="🤖 Автоопределение", callback_data="memory_menu:add_auto")],
            [InlineKeyboardButton(text="📋 Показать всё", callback_data="memory_menu:show")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def memory_category_keyboard() -> InlineKeyboardMarkup:
    """Inline category picker used as a fallback when auto-detection is not used."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📌 Факт", callback_data="mem_cat:fact"),
                InlineKeyboardButton(text="❤️ Предпочтение", callback_data="mem_cat:preference"),
            ],
            [
                InlineKeyboardButton(text="📝 Заметка", callback_data="mem_cat:note"),
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


def task_quick_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏰ Через 5 минут", callback_data="task_time:5m")],
            [InlineKeyboardButton(text="⏰ Через час", callback_data="task_time:1h")],
            [InlineKeyboardButton(text="📅 Завтра в 9:00", callback_data="task_time:tomorrow9")],
            [InlineKeyboardButton(text="🔁 Каждый день 7:00", callback_data="task_time:daily7")],
            [InlineKeyboardButton(text="🔁 Будние дни 9:00", callback_data="task_time:weekday9")],
            [InlineKeyboardButton(text="🔁 Пятница 18:00", callback_data="task_time:friday18")],
            [InlineKeyboardButton(text="✏️ Другое время", callback_data="task_time:manual")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def note_quick_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Ввести заметку", callback_data="note_quick:manual")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def monitor_interval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="5 минут", callback_data="mon_int:5m")],
            [InlineKeyboardButton(text="15 минут", callback_data="mon_int:15m")],
            [InlineKeyboardButton(text="1 час", callback_data="mon_int:1h")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def done_keyboard() -> InlineKeyboardMarkup:
    """Single 'Done' button that returns to main menu conceptually."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово", callback_data="done")],
        ]
    )


def image_actions_keyboard(image_id: int) -> InlineKeyboardMarkup:
    """Inline actions shown under a processed image: save to memory or dismiss."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧠 Сохранить в память",
                    callback_data=f"img_save:{image_id}",
                ),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="img_close"),
            ],
        ]
    )
