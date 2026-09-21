from __future__ import annotations

from datetime import datetime, timezone

from database.models import (
    DISTRICT_LABELS,
    District,
    HousingType,
    Profile,
    RoommateGender,
)

HOUSING_LABELS = {
    HousingType.ROOM: "🛏 своя комната",
    HousingType.SUBLET: "👥 подселение / койко-место",
    HousingType.APARTMENT: "🏢 квартира",
    HousingType.ANY: "🤷 неважно",
}

ROOMMATE_LABELS = {
    RoommateGender.FEMALE: "👩 к девушке",
    RoommateGender.MALE: "👨 к парню",
    RoommateGender.COUPLE: "💑 к паре",
    RoommateGender.ANY: "🤷 неважно",
}


def utcnow() -> datetime:
    """Наивный UTC datetime для хранения в SQLite. datetime.utcnow()
    помечен deprecated начиная с Python 3.12 — это современная замена,
    без расхождений между naive/aware при сравнении с уже сохранёнными
    значениями (SQLite всё равно не хранит timezone)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_positive_int(text: str, *, min_value: int = 1, max_value: int = 1_000_000) -> int | None:
    """Возвращает int, если текст — корректное число в допустимом диапазоне, иначе None."""
    text = text.strip()
    if not text.isdigit():
        return None
    value = int(text)
    if not (min_value <= value <= max_value):
        return None
    return value


def format_profile_summary(profile: Profile, districts: list[District]) -> str:
    gender_label = "👩 Девушка" if profile.gender.value == "female" else "👨 Мужчина"
    districts_label = ", ".join(DISTRICT_LABELS[d] for d in districts) or "не выбраны"

    lines = [
        "👤 <b>Твоя анкета</b>",
        f"Пол: {gender_label}",
        f"🎂 Возраст: {profile.age}",
        f"💰 Бюджет: до ${profile.max_budget}",
        f"📍 Районы: {districts_label}",
        f"Ищу: {HOUSING_LABELS[profile.housing_type]}",
    ]

    # "К кому подселиться" не имеет смысла для квартиры целиком — там не
    # подселяются к соседям (тот же принцип, что и в handlers/profile.py:
    # при выборе "Квартира" этот вопрос вообще не задаётся, а пол соседей
    # автоматически проставляется в "неважно"). Показывать здесь
    # "неважно" для квартиры было бы просто лишней, ничего не значащей
    # строкой.
    if profile.housing_type != HousingType.APARTMENT:
        lines.append(f"К кому подселиться: {ROOMMATE_LABELS[profile.preferred_roommate_gender]}")

    lines += [
        f"🐾 Животные: {'да' if profile.pets else 'нет'}",
        f"🚬 Курение: {'да' if profile.smoking else 'нет'}",
        f"⚠️ Вредные привычки: {'да' if profile.bad_habits else 'нет'}",
    ]
    if profile.occupation:
        lines.append(f"💼 Работа/учёба: {profile.occupation}")
    if profile.description:
        lines.append(f"📝 О себе: {profile.description}")
    return "\n".join(lines)
