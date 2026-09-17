from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from database import crud
from database.database import session_scope
from database.models import District, RoommateGender
from handlers.profile import start_profile
from keyboards.inline import (
    districts_kb,
    listing_card_kb,
    quick_budget_kb,
    roommate_gender_kb,
    search_entry_choice_kb,
)
from keyboards.main import BTN_FAVORITES, BTN_SEARCH, main_menu_kb
from services.formatting import format_listing_card
from services.listings import search_and_store
from sources.kufar import KufarSource
from services.matching import QuickProfile, explain_match, match_listing
from states.quick_search import QuickSearchForm
from states.search import SearchSession
from utils.helpers import parse_positive_int

logger = logging.getLogger(__name__)
router = Router(name="search")


# --------------------------------------------------------------------------
# Точка входа: «🏠 Найти жильё» — если анкеты нет, предлагаем выбор,
# а не просто отправляем заполнять её (Version 1.1, п.E)
# --------------------------------------------------------------------------

@router.message(F.text == BTN_SEARCH)
async def start_search(
    message: Message, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    async with session_scope(session_factory) as session:
        profile = await crud.get_profile_by_telegram_id(session, message.from_user.id)

    if profile is None:
        await message.answer(
            "У тебя ещё нет анкеты. Можно быстро — 3 вопроса и сразу "
            "результаты, или заполнить анкету один раз для точного и "
            "повторяемого поиска.",
            reply_markup=search_entry_choice_kb(),
        )
        return

    districts = [pd.district for pd in profile.districts]
    await _run_search(
        message=message,
        state=state,
        session_factory=session_factory,
        districts=districts,
        profile_source="db",
    )


@router.callback_query(F.data == "entry:profile")
async def entry_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.delete()
    await start_profile(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "entry:quick")
async def entry_quick(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(QuickSearchForm.budget)
    await callback.message.edit_text("Какой у тебя бюджет?")
    await callback.message.answer("Выбери или укажи свой:", reply_markup=quick_budget_kb())
    await callback.answer()


@router.message(Command("quicksearch"))
async def cmd_quick_search(message: Message, state: FSMContext) -> None:
    """Быстрый поиск по требованию, независимо от того, есть ли анкета —
    удобно для разового поиска с другими параметрами, не трогая
    сохранённую анкету (и заодно единственный способ проверить этот
    сценарий, если анкета уже заполнена — обычная кнопка «Найти жильё»
    в этом случае сразу уходит в поиск по анкете, минуя выбор)."""
    await state.set_state(QuickSearchForm.budget)
    await message.answer("⚡ Быстрый поиск\n\nКакой у тебя бюджет?", reply_markup=quick_budget_kb())


# --------------------------------------------------------------------------
# Быстрый поиск: бюджет → районы → пол соседей → сразу результаты
# --------------------------------------------------------------------------

@router.callback_query(QuickSearchForm.budget, F.data.startswith("qbudget:"))
async def quick_budget_preset(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]

    if value == "custom":
        await callback.message.edit_text("Напиши свой бюджет числом (в долларах), например: 180")
        await callback.answer()
        return

    await state.update_data(quick_budget=int(value), selected_districts=[])
    await state.set_state(QuickSearchForm.districts)
    await callback.message.edit_text(f"Бюджет: до ${value} ✅")
    await callback.message.answer(
        "Какие районы интересуют? Можно несколько:", reply_markup=districts_kb(set())
    )
    await callback.answer()


@router.message(QuickSearchForm.budget)
async def quick_budget_text(message: Message, state: FSMContext) -> None:
    budget = parse_positive_int(message.text or "", min_value=10, max_value=5000)
    if budget is None:
        await message.answer("Введи число, например: 180")
        return

    await state.update_data(quick_budget=budget, selected_districts=[])
    await state.set_state(QuickSearchForm.districts)
    await message.answer(
        "Какие районы интересуют? Можно несколько:", reply_markup=districts_kb(set())
    )


@router.callback_query(QuickSearchForm.districts, F.data.startswith("district:toggle:"))
async def quick_toggle_district(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 2)[2]
    data = await state.get_data()
    selected = set(data.get("selected_districts", []))

    if value == "any":
        selected = set() if "any" in selected else {"any"}
    else:
        selected.discard("any")
        if value in selected:
            selected.discard(value)
        else:
            selected.add(value)

    await state.update_data(selected_districts=list(selected))
    selected_enum = {District(v) for v in selected}
    await callback.message.edit_reply_markup(reply_markup=districts_kb(selected_enum))
    await callback.answer()


@router.callback_query(QuickSearchForm.districts, F.data == "district:done")
async def quick_finish_districts(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("selected_districts"):
        await callback.answer("Выбери хотя бы один район (или «Любой»)", show_alert=True)
        return

    await state.set_state(QuickSearchForm.roommate_gender)
    await callback.message.edit_text("Районы выбраны ✅")
    await callback.message.answer("Кого ищешь в соседи?", reply_markup=roommate_gender_kb())
    await callback.answer()


@router.callback_query(QuickSearchForm.roommate_gender, F.data.startswith("roommate:"))
async def quick_finish(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()

    quick_profile = QuickProfile(
        max_budget=data["quick_budget"],
        preferred_roommate_gender=RoommateGender(value),
    )
    districts = [District(v) for v in data["selected_districts"]]

    await callback.message.edit_text("Ищу подходящие варианты на Kufar, немного подожди…")

    await _run_search(
        message=callback.message,
        state=state,
        session_factory=session_factory,
        districts=districts,
        profile_source="quick",
        quick_profile=quick_profile,
        status_message_already_shown=True,
    )
    await callback.answer()


# --------------------------------------------------------------------------
# Общий поиск: используется и обычной анкетой, и быстрым поиском
# --------------------------------------------------------------------------

async def _run_search(
    *,
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker,
    districts: list[District],
    profile_source: str,  # "db" | "quick"
    quick_profile: QuickProfile | None = None,
    status_message_already_shown: bool = False,
) -> None:
    status_msg = None
    if not status_message_already_shown:
        status_msg = await message.answer("Ищу подходящие варианты на Kufar, немного подожди…")

    async with session_scope(session_factory) as session:
        if profile_source == "db":
            # Профиль привязан к предыдущей сессии — перечитаем в текущей,
            # чтобы SQLAlchemy не путал identity map между сессиями.
            profile = await crud.get_profile_by_telegram_id(session, message.chat.id)
        else:
            profile = quick_profile

        candidates = await search_and_store(session, districts, housing_type=profile.housing_type)

        explanations: dict[str, dict] = {}
        matched_ids: list[int] = []
        for listing in candidates:
            if not match_listing(profile, listing):
                continue
            explanation = explain_match(profile, listing)
            explanations[str(listing.id)] = explanation.to_dict()
            matched_ids.append(listing.id)

    if status_msg:
        await status_msg.delete()

    if not matched_ids:
        await message.answer(
            "Пока не нашёл подходящих вариантов 😔 Попробуй позже — "
            "объявления на Kufar обновляются постоянно.",
            reply_markup=main_menu_kb(),
        )
        return

    matched_ids.sort(key=lambda lid: explanations[str(lid)]["score"], reverse=True)

    await state.set_state(SearchSession.browsing)
    await state.update_data(
        listing_ids=matched_ids,
        explanations=explanations,
        index=0,
        card_message_id=None,
        source="search",
    )

    await _show_card(chat_id=message.chat.id, bot=message.bot, state=state, session_factory=session_factory)


# --------------------------------------------------------------------------
# «❤️ Сохранённые» — тот же механизм карточек, без score (см. formatting.py)
# --------------------------------------------------------------------------

@router.message(F.text == BTN_FAVORITES)
async def show_favorites(
    message: Message, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    async with session_scope(session_factory) as session:
        user = await crud.get_or_create_user(
            session, telegram_id=message.from_user.id, username=None, first_name=None
        )
        listings = await crud.get_favorite_listings(session, user.id)

    if not listings:
        await message.answer(
            "Пока нет сохранённых объявлений — жми ❤️ на карточках при поиске.",
            reply_markup=main_menu_kb(),
        )
        return

    listing_ids = [listing.id for listing in listings]

    await message.answer(f"❤️ Сохранённых объявлений: {len(listing_ids)}")

    await state.set_state(SearchSession.browsing)
    await state.update_data(
        listing_ids=listing_ids, explanations={}, index=0, card_message_id=None, source="favorites"
    )

    await _show_card(chat_id=message.chat.id, bot=message.bot, state=state, session_factory=session_factory)


# --------------------------------------------------------------------------
# Показ карточки — общий для поиска, быстрого поиска и избранного.
# Explanation берём из уже посчитанного state (не пересчитываем на каждый
# клик и не зависим от того, есть ли вообще сохранённая анкета в БД —
# для быстрого поиска её нет и не будет).
# --------------------------------------------------------------------------

async def _show_card(
    *,
    chat_id: int,
    bot: Bot,
    state: FSMContext,
    session_factory: async_sessionmaker,
) -> None:
    data = await state.get_data()
    listing_ids: list[int] = data["listing_ids"]
    index: int = data["index"]
    listing_id = listing_ids[index]
    old_message_id = data.get("card_message_id")

    async with session_scope(session_factory) as session:
        listing = await crud.get_listing(session, listing_id)
        user = await crud.get_or_create_user(
            session, telegram_id=chat_id, username=None, first_name=None
        )
        favorited = await crud.is_favorited(session, user.id, listing_id)
        text = format_listing_card(listing, position=(index + 1, len(listing_ids)))
        kb = listing_card_kb(
            has_prev=index > 0,
            has_next=index < len(listing_ids) - 1,
            is_favorited=favorited,
            listing_url=listing.url,
        )
        image_url = listing.image_url
        listing_url = listing.url

    if old_message_id:
        ids = old_message_id if isinstance(old_message_id, list) else [old_message_id]
        for mid in ids:
            try:
                await bot.delete_message(chat_id, mid)
            except TelegramBadRequest:
                pass  # сообщение уже удалено/устарело — не критично

    # Собираем список URL кандидатов на фото (превью +, если получится,
    # вся галерея объявления), а затем СКАЧИВАЕМ их сами и грузим в
    # Telegram уже готовым файлом, а не голой ссылкой (см. докстринг
    # KufarSource.download_photos в sources/kufar.py — реальный найденный
    # баг: Telegram не мог сам вытянуть картинку с нового CDN Kufar по
    # прямой ссылке, из-за чего карточки приходили вообще без фото).
    photo_urls: list[str] = []
    if image_url:
        try:
            extra = await KufarSource().fetch_photos(listing_url)
            photo_urls = extra if extra else [image_url]
        except Exception as exc:
            logger.warning("Не удалось получить доп. фото для %s (%s)", listing_url, exc)
            photo_urls = [image_url]

    photo_bytes: list[bytes] = []
    if photo_urls:
        try:
            photo_bytes = await KufarSource().download_photos(photo_urls[:5])
        except Exception as exc:
            logger.warning("Не удалось скачать фото для %s (%s)", listing_url, exc)

    sent_ids: list[int] = []
    if len(photo_bytes) >= 2:
        media = [
            InputMediaPhoto(media=BufferedInputFile(data_, filename=f"photo_{i}.jpg"))
            for i, data_ in enumerate(photo_bytes)
        ]
        try:
            msgs = await bot.send_media_group(chat_id, media=media)
            sent_ids = [m.message_id for m in msgs]
            btn_msg = await bot.send_message(chat_id, text, reply_markup=kb)
            sent_ids.append(btn_msg.message_id)
        except TelegramBadRequest as exc:
            logger.warning("Не удалось отправить альбом фото (%s), пробую одним фото", exc)
            photo_bytes = photo_bytes[:1]

    if not sent_ids:
        if photo_bytes:
            try:
                sent = await bot.send_photo(
                    chat_id,
                    photo=BufferedInputFile(photo_bytes[0], filename="photo.jpg"),
                    caption=text,
                    reply_markup=kb,
                )
                sent_ids = [sent.message_id]
            except TelegramBadRequest as exc:
                logger.warning("Не удалось отправить фото (%s), отправляю текстом", exc)
        if not sent_ids:
            sent = await bot.send_message(chat_id, text, reply_markup=kb)
            sent_ids = [sent.message_id]

    await state.update_data(card_message_id=sent_ids)


@router.callback_query(SearchSession.browsing, F.data == "card:next")
async def next_card(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    data = await state.get_data()
    await state.update_data(index=min(data["index"] + 1, len(data["listing_ids"]) - 1))
    await _show_card(
        chat_id=callback.message.chat.id, bot=callback.bot, state=state, session_factory=session_factory
    )
    await callback.answer()


@router.callback_query(SearchSession.browsing, F.data == "card:prev")
async def prev_card(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    data = await state.get_data()
    await state.update_data(index=max(data["index"] - 1, 0))
    await _show_card(
        chat_id=callback.message.chat.id, bot=callback.bot, state=state, session_factory=session_factory
    )
    await callback.answer()


@router.callback_query(SearchSession.browsing, F.data == "card:fav")
async def toggle_fav(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    data = await state.get_data()
    listing_ids: list[int] = data["listing_ids"]
    index: int = data["index"]
    listing_id = listing_ids[index]
    source = data.get("source", "search")

    async with session_scope(session_factory) as session:
        user = await crud.get_or_create_user(
            session, telegram_id=callback.message.chat.id, username=None, first_name=None
        )
        now_favorited = await crud.toggle_favorite(session, user.id, listing_id)

    await callback.answer("Сохранено ❤️" if now_favorited else "Убрано из сохранённых")

    if source == "favorites" and not now_favorited:
        # Мы именно в разделе «Сохранённые» и только что убрали текущую
        # карточку из избранного — логичнее сразу убрать её из списка,
        # а не просто перерисовать с тем же ❤️/💔.
        listing_ids = [lid for lid in listing_ids if lid != listing_id]

        if not listing_ids:
            await state.clear()
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                pass
            await callback.message.answer(
                "Сохранённых объявлений больше нет.", reply_markup=main_menu_kb()
            )
            return

        new_index = min(index, len(listing_ids) - 1)
        await state.update_data(listing_ids=listing_ids, index=new_index)

    await _show_card(
        chat_id=callback.message.chat.id, bot=callback.bot, state=state, session_factory=session_factory
    )


@router.callback_query(SearchSession.browsing, F.data == "card:restart")
async def restart_search(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    await state.clear()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.message.answer("Возвращаемся в меню 🙂", reply_markup=main_menu_kb())
    await callback.answer()


# --------------------------------------------------------------------------
# Ответ на уведомление ("Нашёл N вариантов — показать?", см.
# services/notifications.py). Результат лежит в БД (PendingNotification),
# а не в FSM — состояние диалога выставляем ЗДЕСЬ, только в ответ на явный
# клик пользователя, а не заранее из фонового цикла (иначе рисковали бы
# молча прервать то, чем человек занят прямо сейчас — см. докстринг
# services/notifications.py).
# --------------------------------------------------------------------------

@router.callback_query(F.data == "notif:show")
async def show_notification_results(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    async with session_scope(session_factory) as session:
        user = await crud.get_or_create_user(
            session, telegram_id=callback.from_user.id, username=None, first_name=None
        )
        pending = await crud.get_pending_notification(session, user.id)
        if pending is not None:
            await crud.clear_pending_notification(session, user.id)

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    if pending is None:
        # Например, два клика подряд, или находка уже устарела и была
        # заменена более свежей (см. crud.set_pending_notification).
        await callback.message.answer(
            "Эти варианты уже не актуальны — попробуй обычный поиск через «🏠 Найти жильё».",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    listing_ids, explanations = pending
    await state.set_state(SearchSession.browsing)
    await state.update_data(
        listing_ids=listing_ids,
        explanations=explanations,
        index=0,
        card_message_id=None,
        source="notification",
    )
    await _show_card(
        chat_id=callback.message.chat.id, bot=callback.bot, state=state, session_factory=session_factory
    )
    await callback.answer()


@router.callback_query(F.data == "notif:dismiss")
async def dismiss_notification_results(
    callback: CallbackQuery, session_factory: async_sessionmaker
) -> None:
    async with session_scope(session_factory) as session:
        user = await crud.get_or_create_user(
            session, telegram_id=callback.from_user.id, username=None, first_name=None
        )
        await crud.clear_pending_notification(session, user.id)

    # Удаляем, а не оставляем висеть отредактированным "ок" — раньше эти
    # подтверждения тоже копились в чате отдельными сообщениями.
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        await callback.message.edit_text("Хорошо, пропускаем эти варианты.")
    await callback.answer()
