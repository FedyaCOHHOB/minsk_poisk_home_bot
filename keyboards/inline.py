from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import DISTRICT_LABELS, District


def gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👩 Девушка", callback_data="gender:female"),
                InlineKeyboardButton(text="👨 Мужчина", callback_data="gender:male"),
            ]
        ]
    )


def housing_type_kb() -> InlineKeyboardMarkup:
    """Верхний уровень выбора — ровно как на Kufar: там реально только
    две категории объявлений, «Комнаты» и «Квартиры» (см. докстринг
    sources/kufar.py). Если выбрана «Комната» — это ещё не финальный
    ответ, а переход к уточняющему шагу (см. room_type_kb ниже), чтобы
    не мешать в одну кучу два разных вопроса («что за жильё» и «своя
    комната или с подселением»)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏢 Квартиру целиком", callback_data="housing:apartment")],
            [InlineKeyboardButton(text="🚪 Комнату", callback_data="housing:room")],
            [InlineKeyboardButton(text="🤷 Неважно", callback_data="housing:any")],
        ]
    )


def room_type_kb() -> InlineKeyboardMarkup:
    """Уточнение ПОСЛЕ того как на верхнем уровне выбрали «Комната» —
    Kufar их структурно не различает (одна и та же категория объявлений),
    но для человека разница принципиальная: своя комната целиком или
    подселение/койко-место к кому-то ещё."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛏 Своя комната", callback_data="roomtype:room")],
            [InlineKeyboardButton(text="👥 Подселение / койко-место", callback_data="roomtype:sublet")],
        ]
    )


def roommate_gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👩 К девушке", callback_data="roommate:female")],
            [InlineKeyboardButton(text="👨 К парню", callback_data="roommate:male")],
            [InlineKeyboardButton(text="💑 К паре", callback_data="roommate:couple")],
            [InlineKeyboardButton(text="🤷 Неважно", callback_data="roommate:any")],
        ]
    )


def yes_no_kb(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"yesno:{field}:yes"),
                InlineKeyboardButton(text="🚫 Нет", callback_data=f"yesno:{field}:no"),
            ]
        ]
    )


def skip_kb(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip:{field}")]
        ]
    )


def districts_kb(selected: set[District]) -> InlineKeyboardMarkup:
    """Мультивыбор районов. Отмеченные — с галочкой. 'Любой' сбрасывает остальные."""
    rows: list[list[InlineKeyboardButton]] = []

    any_mark = "✅ " if District.ANY in selected else ""
    rows.append(
        [
            InlineKeyboardButton(
                text=f"{any_mark}🗺 Любой район", callback_data="district:toggle:any"
            )
        ]
    )

    others = [d for d in District if d != District.ANY]
    for i in range(0, len(others), 2):
        row = []
        for d in others[i : i + 2]:
            mark = "✅ " if d in selected else ""
            row.append(
                InlineKeyboardButton(
                    text=f"{mark}{DISTRICT_LABELS[d]}",
                    callback_data=f"district:toggle:{d.value}",
                )
            )
        rows.append(row)

    rows.append(
        [InlineKeyboardButton(text="✅ Готово", callback_data="district:done")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def listing_card_kb(
    *, has_prev: bool, has_next: bool, is_favorited: bool, listing_url: str
) -> InlineKeyboardMarkup:
    fav_text = "💔 Убрать из сохранённых" if is_favorited else "❤️ Сохранить"

    nav_row = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="card:prev"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Следующее ➡️", callback_data="card:next"))

    rows = [
        [InlineKeyboardButton(text="🔗 Открыть объявление", url=listing_url)],
        [InlineKeyboardButton(text=fav_text, callback_data="card:fav")],
    ]
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🏠 Вернуться к поиску", callback_data="card:restart")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_entry_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Быстрый поиск", callback_data="entry:quick")],
            [InlineKeyboardButton(text="👤 Заполнить анкету", callback_data="entry:profile")],
        ]
    )


def quick_budget_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="До $100", callback_data="qbudget:100"),
                InlineKeyboardButton(text="До $150", callback_data="qbudget:150"),
            ],
            [
                InlineKeyboardButton(text="До $200", callback_data="qbudget:200"),
                InlineKeyboardButton(text="До $300", callback_data="qbudget:300"),
            ],
            [InlineKeyboardButton(text="Другой", callback_data="qbudget:custom")],
        ]
    )


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить анкету", callback_data="settings:edit_profile")],
            [InlineKeyboardButton(text="🗑 Удалить анкету", callback_data="settings:delete_profile")],
            [InlineKeyboardButton(text="⚠️ Удалить все мои данные", callback_data="settings:delete_all")],
        ]
    )


def confirm_delete_profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить", callback_data="settings:delete_profile:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="settings:delete_profile:cancel"),
            ]
        ]
    )


def confirm_delete_all_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить всё", callback_data="settings:delete_all:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="settings:delete_all:cancel"),
            ]
        ]
    )


def notifications_kb(is_active: bool) -> InlineKeyboardMarkup:
    if is_active:
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔕 Выключить", callback_data="notif:disable")]]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔔 Включить", callback_data="notif:enable")]]
    )
