"""SQLAlchemy ORM-модели для MVP.

Схема соответствует Этапу 1 (архитектура):
    users, profiles, profile_districts, listings, favorites

listings и favorites уже описаны здесь, чтобы не переделывать схему на
Этапе 3-4 — но заполняться они начнут только когда появится парсер (sources/)
и сервис matching (services/).
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    """Клиентская (Python) генерация времени вместо server_default=func.now()
    — важно именно для Listing.parsed_at, который сравнивается с
    last_checked_at (см. database/crud.py: get_new_listings_since,
    utils.helpers.utcnow — тот же по смыслу хелпер, но продублирован
    здесь напрямую, а не импортирован: utils.helpers сам импортирует из
    database.models, импорт в обратную сторону создал бы циклическую
    зависимость). У SQLite CURRENT_TIMESTAMP/func.now() точность —  целые
    секунды, у Python datetime.now() — микросекунды. При server_default
    объявление, вставленное в базу в ТУ ЖЕ секунду, что и обновление
    last_checked_at, могло получить более раннее по факту сравнения
    время и ошибочно не засчитаться как "новое" в уведомлениях — реальный
    баг, пойманный тестом на редактирование уведомлений."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


class RoommateGender(str, enum.Enum):
    FEMALE = "female"
    MALE = "male"
    COUPLE = "couple"
    ANY = "any"


class HousingType(str, enum.Enum):
    ROOM = "room"          # комната
    SUBLET = "sublet"      # подселение
    APARTMENT = "apartment"  # квартира (отдельная категория на Kufar — не просто фильтр)
    ANY = "any"            # неважно


class District(str, enum.Enum):
    ANY = "any"
    CENTRALNY = "central"
    FRUNZENSKY = "frunzensky"
    MOSKOVSKY = "moskovsky"
    OKTYABRSKY = "oktyabrsky"
    LENINSKY = "leninsky"
    ZAVODSKOY = "zavodskoy"
    PERVOMAYSKY = "pervomaysky"
    SOVETSKY = "sovetsky"
    PARTIZANSKY = "partizansky"


DISTRICT_LABELS: dict[District, str] = {
    District.ANY: "Любой район",
    District.CENTRALNY: "Центральный",
    District.FRUNZENSKY: "Фрунзенский",
    District.MOSKOVSKY: "Московский",
    District.OKTYABRSKY: "Октябрьский",
    District.LENINSKY: "Ленинский",
    District.ZAVODSKOY: "Заводской",
    District.PERVOMAYSKY: "Первомайский",
    District.SOVETSKY: "Советский",
    District.PARTIZANSKY: "Партизанский",
}


# --------------------------------------------------------------------------
# Таблицы
# --------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    profile: Mapped["Profile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    favorites: Mapped[list["Favorite"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    gender: Mapped[Gender] = mapped_column(Enum(Gender))
    age: Mapped[int] = mapped_column(Integer)
    max_budget: Mapped[int] = mapped_column(Integer)
    housing_type: Mapped[HousingType] = mapped_column(Enum(HousingType))
    preferred_roommate_gender: Mapped[RoommateGender] = mapped_column(Enum(RoommateGender))

    pets: Mapped[bool] = mapped_column(Boolean, default=False)
    smoking: Mapped[bool] = mapped_column(Boolean, default=False)
    bad_habits: Mapped[bool] = mapped_column(Boolean, default=False)

    occupation: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile")
    districts: Mapped[list["ProfileDistrict"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class ProfileDistrict(Base):
    """Многие-ко-многим: одна анкета — несколько районов."""

    __tablename__ = "profile_districts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE")
    )
    district: Mapped[District] = mapped_column(Enum(District))

    profile: Mapped["Profile"] = relationship(back_populates="districts")

    __table_args__ = (UniqueConstraint("profile_id", "district"),)


class Listing(Base):
    """Заполняется парсером на Этапе 3. Модель нужна уже сейчас, чтобы
    не переделывать миграции позже."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32))

    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = "Договорная"
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    city: Mapped[str] = mapped_column(String(64), default="Минск")
    district: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    housing_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    roommates_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suitable_gender: Mapped[str | None] = mapped_column(String(16), nullable=True)

    url: Mapped[str] = mapped_column(String(512))
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("external_id", "source"),)


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="favorites")
    listing: Mapped["Listing"] = relationship()

    __table_args__ = (UniqueConstraint("user_id", "listing_id"),)


class NotificationSubscription(Base):
    """Одна подписка на пользователя — вкл/выкл, без множественных
    подписок с разными параметрами (для MVP этого достаточно, критерии
    поиска берутся из Profile пользователя, а не хранятся здесь отдельно)."""

    __tablename__ = "notification_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    min_score: Mapped[int] = mapped_column(Integer, default=70)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PendingNotification(Base):
    """Найденные фоновым циклом объявления, которые ждут ответа
    "Показать"/"Не сейчас" от пользователя (см. services/notifications.py).

    Хранится в БД, а НЕ пишется напрямую в FSM пользователя в момент
    находки — иначе фоновый цикл рисковал бы молча прервать то, чем
    человек занят ПРЯМО СЕЙЧАС (например, как раз заполняет анкету), если
    уведомление совпадёт по времени с активным диалогом. FSM-состояние
    трогаем только в ответ на явный клик по кнопке "Показать" — тогда
    это осознанное действие самого пользователя, а не вмешательство
    в фоне без его ведома."""

    __tablename__ = "pending_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    listing_ids_json: Mapped[str] = mapped_column(Text)
    explanations_json: Mapped[str] = mapped_column(Text)
    # ID сообщения-сводки в Telegram ("Нашёл N — показать?"), если уже
    # отправлялось. Нужен, чтобы следующая находка РЕДАКТИРОВАЛА то же
    # сообщение вместо отправки нового — иначе за день накапливался бы
    # десяток отдельных уведомлений подряд (выглядит как мусор в чате), и
    # каждое новое сообщение отдельно пинговало бы пользователя звуком —
    # а редактирование существующего сообщения в Telegram проходит тихо,
    # без повторного уведомления на телефоне.
    summary_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
