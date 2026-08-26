from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_SEARCH = "🏠 Найти жильё"
BTN_PROFILE = "👤 Моя анкета"
BTN_SETTINGS = "⚙️ Настройки"
BTN_FAVORITES = "❤️ Сохранённые"
BTN_HELP = "ℹ️ Помощь"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_PROFILE)],
            [KeyboardButton(text=BTN_FAVORITES), KeyboardButton(text=BTN_SETTINGS)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )
