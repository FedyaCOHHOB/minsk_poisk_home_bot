"""Функции доступа к данным. Хендлеры не работают с ORM напрямую —
только через эти функции."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    District,
    Favorite,
    Gender,
    HousingType,
    Listing,
    NotificationSubscription,
    PendingNotification,
    Profile,
    ProfileDistrict,
    RoommateGender,
    User,
)
from sources.schemas import RawListing
from utils.helpers import utcnow


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user is not None:
        # обновим username/first_name, только если реально переданы —
        # иначе легко случайно затереть их None при повторных вызовах
        # (например, из хендлеров, где под рукой нет message.from_user).
        if username is not None:
            user.username = username
        if first_name is not None:
            user.first_name = first_name
        # updated_at трогаем ВСЕГДА, а не только при реальном изменении
        # полей — иначе SQLAlchemy может не выдать UPDATE (нет изменений =
        # нет записи), и метрика "активных за N дней" в /stats будет врать.
        user.updated_at = utcnow()
        return user

    user = User(telegram_id=telegram_id, username=username, first_name=first_name)
    session.add(user)
    await session.flush()  # чтобы получить user.id до коммита
    return user


async def get_profile_by_telegram_id(
    session: AsyncSession, telegram_id: int
) -> Profile | None:
    result = await session.execute(
        select(Profile)
        .join(User)
        .where(User.telegram_id == telegram_id)
        .options(selectinload(Profile.districts))
    )
    return result.scalar_one_or_none()


async def upsert_listing(session: AsyncSession, raw: RawListing) -> Listing:
    """Апсерт по (external_id, source) — не плодим дубликаты при повторном поиске."""
    result = await session.execute(
        select(Listing).where(
            Listing.external_id == raw.external_id, Listing.source == raw.source
        )
    )
    listing = result.scalar_one_or_none()

    if listing is None:
        listing = Listing(external_id=raw.external_id, source=raw.source)
        session.add(listing)

    listing.title = raw.title
    listing.description = raw.description
    listing.price = raw.price
    listing.currency = raw.currency
    listing.district = raw.district
    listing.url = raw.url
    listing.image_url = raw.image_url
    listing.housing_type = raw.housing_type
    listing.is_active = True

    await session.flush()
    return listing


async def get_listing(session: AsyncSession, listing_id: int) -> Listing | None:
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    return result.scalar_one_or_none()


async def is_favorited(session: AsyncSession, user_id: int, listing_id: int) -> bool:
    result = await session.execute(
        select(Favorite).where(
            Favorite.user_id == user_id, Favorite.listing_id == listing_id
        )
    )
    return result.scalar_one_or_none() is not None


async def toggle_favorite(session: AsyncSession, user_id: int, listing_id: int) -> bool:
    """Возвращает True, если после вызова объявление в избранном, False — если убрали."""
    result = await session.execute(
        select(Favorite).where(
            Favorite.user_id == user_id, Favorite.listing_id == listing_id
        )
    )
    favorite = result.scalar_one_or_none()

    if favorite is not None:
        await session.delete(favorite)
        await session.flush()
        return False

    session.add(Favorite(user_id=user_id, listing_id=listing_id))
    await session.flush()
    return True


async def upsert_profile(
    session: AsyncSession,
    user: User,
    *,
    gender: Gender,
    age: int,
    max_budget: int,
    housing_type: HousingType,
    preferred_roommate_gender: RoommateGender,
    pets: bool,
    smoking: bool,
    bad_habits: bool,
    occupation: str | None,
    description: str | None,
    districts: list[District],
) -> Profile:
    """Создаёт анкету или полностью перезаписывает существующую."""
    result = await session.execute(
        select(Profile).where(Profile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = Profile(user_id=user.id)
        session.add(profile)

    profile.gender = gender
    profile.age = age
    profile.max_budget = max_budget
    profile.housing_type = housing_type
    profile.preferred_roommate_gender = preferred_roommate_gender
    profile.pets = pets
    profile.smoking = smoking
    profile.bad_habits = bad_habits
    profile.occupation = occupation
    profile.description = description

    await session.flush()  # нужен profile.id для districts

    # пересобираем districts с нуля — проще, чем диффать список.
    # Прямой DELETE через core, а не обход ORM-коллекции: обращение к
    # ленивому relationship в AsyncSession без eager-load упадёт с
    # MissingGreenlet.
    await session.execute(
        delete(ProfileDistrict).where(ProfileDistrict.profile_id == profile.id)
    )

    for district in districts:
        session.add(ProfileDistrict(profile_id=profile.id, district=district))

    await session.flush()
    return profile


# --------------------------------------------------------------------------
# Статистика — для /stats
# --------------------------------------------------------------------------

async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def count_profiles(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Profile))
    return result.scalar_one()


async def count_listings(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Listing))
    return result.scalar_one()


async def count_favorites(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Favorite))
    return result.scalar_one()


async def count_active_users_since(session: AsyncSession, since: datetime) -> int:
    result = await session.execute(
        select(func.count()).select_from(User).where(User.updated_at >= since)
    )
    return result.scalar_one()


async def get_favorite_listings(session: AsyncSession, user_id: int) -> list[Listing]:
    """Сохранённые объявления пользователя, новые сверху."""
    result = await session.execute(
        select(Listing)
        .join(Favorite, Favorite.listing_id == Listing.id)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_profile(session: AsyncSession, telegram_id: int) -> bool:
    """Удаляет анкету (и её districts) пользователя. Самого User и его
    Favorites не трогаем — это разные сущности, удаление анкеты не должно
    сносить сохранённые объявления. Возвращает True, если что-то реально
    удалили."""
    result = await session.execute(
        select(Profile).join(User).where(User.telegram_id == telegram_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        return False

    # Явный DELETE, а не обход ORM-коллекции — тот же принцип, что и в
    # upsert_profile: обращение к ленивому relationship в AsyncSession
    # без eager-load падает с MissingGreenlet.
    await session.execute(delete(ProfileDistrict).where(ProfileDistrict.profile_id == profile.id))
    await session.delete(profile)
    await session.flush()
    return True


# --------------------------------------------------------------------------
# Уведомления
# --------------------------------------------------------------------------

async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_profile_by_user_id(session: AsyncSession, user_id: int) -> Profile | None:
    """Как get_profile_by_telegram_id, но по внутреннему User.id — нужно
    для фонового цикла уведомлений, где под рукой только user_id из
    NotificationSubscription, а не telegram_id."""
    result = await session.execute(
        select(Profile)
        .where(Profile.user_id == user_id)
        .options(selectinload(Profile.districts))
    )
    return result.scalar_one_or_none()


async def get_subscription(session: AsyncSession, user_id: int) -> NotificationSubscription | None:
    result = await session.execute(
        select(NotificationSubscription).where(NotificationSubscription.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def set_subscription_active(
    session: AsyncSession, user_id: int, active: bool
) -> NotificationSubscription:
    sub = await get_subscription(session, user_id)
    if sub is None:
        sub = NotificationSubscription(user_id=user_id, is_active=active, last_checked_at=utcnow())
        session.add(sub)
    else:
        sub.is_active = active
        if active:
            # Включили заново — не шлём разом всё, что накопилось, пока было
            # выключено. Считаем "новым" только то, что появится с этого момента.
            sub.last_checked_at = utcnow()
    await session.flush()
    return sub


async def get_active_subscriptions(session: AsyncSession) -> list[NotificationSubscription]:
    result = await session.execute(
        select(NotificationSubscription).where(NotificationSubscription.is_active == True)  # noqa: E712
    )
    return list(result.scalars().all())


async def update_subscription_checked(
    session: AsyncSession, subscription_id: int, checked_at
) -> None:
    await session.execute(
        update(NotificationSubscription)
        .where(NotificationSubscription.id == subscription_id)
        .values(last_checked_at=checked_at)
    )


async def get_new_listings_since(
    session: AsyncSession, since, districts: list[str] | None = None
) -> list[Listing]:
    """"Новое" = впервые увиденное нами после `since` (Listing.parsed_at
    не трогается при повторных upsert — см. database/crud.upsert_listing —
    так что это надёжная метка первого появления, а не "последнего
    обновления записи")."""
    query = select(Listing).where(Listing.parsed_at > since, Listing.is_active == True)  # noqa: E712
    if districts:
        query = query.where(Listing.district.in_(districts))
    result = await session.execute(query)
    return list(result.scalars().all())


async def delete_user_completely(session: AsyncSession, telegram_id: int) -> bool:
    """Полное удаление пользователя и вообще всех его данных (анкета,
    районы, избранное, подписка на уведомления). Полагается на
    ON DELETE CASCADE в схеме — теперь безопасно, PRAGMA foreign_keys
    включена (см. database/database.py), явно чистить дочерние таблицы
    вручную не нужно."""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user is None:
        return False
    await session.delete(user)
    await session.flush()
    return True


# --------------------------------------------------------------------------
# Отложенные результаты уведомлений (см. докстринг PendingNotification)
# --------------------------------------------------------------------------

async def get_pending_message_id(session: AsyncSession, user_id: int) -> int | None:
    result = await session.execute(
        select(PendingNotification.summary_message_id).where(PendingNotification.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def set_pending_notification(
    session: AsyncSession,
    user_id: int,
    listing_ids: list[int],
    explanations: dict,
    summary_message_id: int,
) -> None:
    result = await session.execute(
        select(PendingNotification).where(PendingNotification.user_id == user_id)
    )
    pending = result.scalar_one_or_none()
    ids_json = json.dumps(listing_ids)
    exp_json = json.dumps(explanations)

    if pending is None:
        pending = PendingNotification(
            user_id=user_id,
            listing_ids_json=ids_json,
            explanations_json=exp_json,
            summary_message_id=summary_message_id,
        )
        session.add(pending)
    else:
        # Если предыдущий цикл уже что-то нашёл, а пользователь ещё не
        # ответил — просто заменяем на более свежую находку, не плодим
        # вторую строку.
        pending.listing_ids_json = ids_json
        pending.explanations_json = exp_json
        pending.summary_message_id = summary_message_id

    await session.flush()


async def get_pending_notification(
    session: AsyncSession, user_id: int
) -> tuple[list[int], dict] | None:
    result = await session.execute(
        select(PendingNotification).where(PendingNotification.user_id == user_id)
    )
    pending = result.scalar_one_or_none()
    if pending is None:
        return None
    return json.loads(pending.listing_ids_json), json.loads(pending.explanations_json)


async def clear_pending_notification(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        delete(PendingNotification).where(PendingNotification.user_id == user_id)
    )
