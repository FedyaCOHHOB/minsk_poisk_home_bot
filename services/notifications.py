"""Фоновая проверка новых объявлений и рассылка уведомлений подписчикам.

Работает только для пользователей с сохранённой анкетой (Profile) — для
быстрого поиска (QuickProfile) подписка не имеет смысла, там нет
постоянных критериев для повторной проверки в фоне.

Раз в CHECK_INTERVAL_MINUTES (кроме тихих часов, см. ниже):
1. Если активных подписок нет вообще — ничего не делаем, не дёргаем Kufar
   впустую.
2. Если есть хотя бы одна — один раз обновляем базу по всем районам и
   категориям (как /update у админа), а не по отдельному запросу на
   каждого подписчика — иначе частота запросов к Kufar росла бы линейно
   с числом пользователей.
3. Для каждой подписки — ищем объявления, которые появились у нас в базе
   позже last_checked_at (см. crud.get_new_listings_since), прогоняем
   через тот же matching, что и обычный поиск. Найденное сохраняется как
   PendingNotification (см. database/models.py) — НЕ пишется напрямую в
   FSM пользователя. Пользователю уходит только короткое сообщение-сводка
   с кнопками "Показать"/"Не сейчас"; сама карточка/пагинация открывается
   только в ответ на явный клик (handlers/search.py: show_notification_results),
   а не молча в фоне. Причина: если писать в FSM прямо из фонового цикла,
   можно случайно прервать то, чем человек занят ПРЯМО СЕЙЧАС (например,
   как раз заполняет анкету) — уведомление совпало бы по времени и молча
   сломало бы его текущий диалог. Через БД такого риска нет: состояние
   диалога трогаем только тогда, когда пользователь сам на это явно
   нажимает.

ТИХИЕ ЧАСЫ: весь цикл целиком пропускается с 23:00 до 08:00 по Минску —
включая сам поход в Kufar (незачем тратить запросы ночью, если разослать
уведомления всё равно нельзя). Пока это фиксированный дефолт для всех, не
настройка на пользователя — риск разбудить кого-то уведомлением в 3 ночи
и получить блокировку бота значимее, чем польза от гибкой настройки прямо
сейчас. last_checked_at у пропущенных подписок не трогается, так что всё
накопленное за ночь корректно найдётся первым же циклом после 08:00 —
никакие "новые" объявления не потеряются, просто уведомление придёт
позже, не мгновенно."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import async_sessionmaker

from database import crud
from database.database import session_scope
from services.listings import update_all_listings
from services.matching import explain_match, match_listing
from utils.helpers import utcnow

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MINUTES = 20
# Потолок на размер одного списка находок за цикл — не защита от спама
# сообщениями (сообщение всегда одно, сводка), а просто разумный лимит,
# чтобы не пытаться впихнуть в пагинацию сотню объявлений разом.
MAX_LISTINGS_PER_CYCLE = 10

MINSK_TZ = timezone(timedelta(hours=3))  # Europe/Minsk, без перехода на летнее время
QUIET_HOURS_START = 23  # с 23:00
QUIET_HOURS_END = 8     # до 08:00


def _is_quiet_hours(now: datetime | None = None) -> bool:
    """now передаётся явно только для тестов — в обычной работе всегда
    берём текущее время сами."""
    hour = (now or datetime.now(MINSK_TZ)).astimezone(MINSK_TZ).hour
    return hour >= QUIET_HOURS_START or hour < QUIET_HOURS_END


def _plural_variants(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "новый вариант"
    if 2 <= count % 10 <= 4 and not (12 <= count % 100 <= 14):
        return "новых варианта"
    return "новых вариантов"


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, показать", callback_data="notif:show"),
                InlineKeyboardButton(text="Не сейчас", callback_data="notif:dismiss"),
            ]
        ]
    )


async def run_notification_cycle(bot: Bot, session_factory: async_sessionmaker) -> None:
    if _is_quiet_hours():
        logger.info("Уведомления: тихие часы (23:00–08:00 по Минску), цикл пропущен")
        return

    async with session_scope(session_factory) as session:
        subscriptions = await crud.get_active_subscriptions(session)

    if not subscriptions:
        return

    logger.info("Уведомления: активных подписок — %s, обновляю базу", len(subscriptions))
    async with session_scope(session_factory) as session:
        await update_all_listings(session)

    for sub in subscriptions:
        await _check_one_subscription(
            bot, session_factory, sub.id, sub.user_id, sub.last_checked_at, sub.min_score
        )


async def _check_one_subscription(
    bot: Bot,
    session_factory: async_sessionmaker,
    subscription_id: int,
    user_id: int,
    last_checked_at,
    min_score: int,
) -> None:
    listing_ids: list[int] = []
    telegram_id: int | None = None

    async with session_scope(session_factory) as session:
        profile = await crud.get_profile_by_user_id(session, user_id)
        if profile is None:
            # Анкету удалили, а подписка осталась — отключаем, чтобы не
            # проверять её впустую на каждом цикле.
            await crud.set_subscription_active(session, user_id, False)
            return

        user = await crud.get_user_by_id(session, user_id)
        if user is None:
            return
        telegram_id = user.telegram_id

        districts = [pd.district.value for pd in profile.districts]
        # "any" в списке означает "любой район" — это НЕ значение, которое
        # реально встречается в Listing.district (см. правку в sources/kufar.py
        # и её докстринг), поэтому фильтровать по нему нельзя — нужно просто
        # не ограничивать по району вообще.
        district_filter = None if "any" in districts else districts
        new_listings = await crud.get_new_listings_since(session, last_checked_at, district_filter)

        scored = []
        for listing in new_listings:
            if not match_listing(profile, listing):
                continue
            explanation = explain_match(profile, listing)
            if explanation.score >= min_score:
                scored.append((listing, explanation))

        scored.sort(key=lambda pair: pair[1].score, reverse=True)
        scored = scored[:MAX_LISTINGS_PER_CYCLE]

        listing_ids = [listing.id for listing, _ in scored]
        explanations = {str(listing.id): exp.to_dict() for listing, exp in scored}

        if listing_ids:
            await crud.set_pending_notification(session, user_id, listing_ids, explanations)

        await crud.update_subscription_checked(session, subscription_id, utcnow())

    if not listing_ids:
        return

    count = len(listing_ids)
    text = f"🔔 Нашёл для тебя {count} {_plural_variants(count)} — показать?"
    try:
        await bot.send_message(telegram_id, text, reply_markup=_confirm_kb())
    except TelegramForbiddenError:
        logger.info("Пользователь %s заблокировал бота — отключаю его подписку", telegram_id)
        async with session_scope(session_factory) as session:
            await crud.set_subscription_active(session, user_id, False)
    except TelegramBadRequest as exc:
        logger.warning("Не удалось отправить уведомление %s: %s", telegram_id, exc)
