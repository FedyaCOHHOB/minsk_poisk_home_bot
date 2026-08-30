"""Сопоставление анкеты пользователя и объявления.

Три уровня:
  match_listing()   — жёсткий фильтр (только бюджет — единственное, что
                       у нас есть как надёжное число, см. докстринг ниже)
  explain_match()   — рейтинг 0..100 РАЗЛОЖЕННЫЙ по критериям, чтобы
                       можно было честно показать пользователю "Почему
                       подходит" (Version 1.1)
  match_score()     — тонкая обёртка над explain_match() для мест, где
                       нужно только число (обратная совместимость)

ВАЖНОЕ ОГРАНИЧЕНИЕ, которое стоит держать в голове:
Kufar не даёт структурированного поля «пол соседей» — у нас есть только
сырой текст объявления. Различение «комната» vs «подселение» — тоже
эвристика по тексту (обе категории вперемешку под /snyat/komnatu). Эти
критерии здесь СОЗНАТЕЛЬНО не участвуют в жёстком фильтре match_listing(),
только в рейтинге: текстовая эвристика может ошибаться (не найти слово
или найти его не в том смысле), и жёстко отбрасывать объявление из-за
этого — значит терять реальные варианты. А вот «квартира» — это
ДОСТОВЕРНЫЙ факт (Kufar отдаёт её отдельной категорией /snyat/kvartiru,
см. sources/kufar.py), не эвристика. Жёсткий фильтр match_listing() —
только по бюджету, который у Kufar есть как число (когда цена не
«Договорная»). Район уже гарантированно верный: мы намеренно ходим
только по URL нужного района, а не угадываем его из текста.

Поэтому там, где эвристика НЕ смогла подтвердить совпадение (например,
объявление просто не упомянуло пол соседей явно), explain_match() не
утверждает "не подходит" — честно помечает как "не уточнено", а не как
жёсткий минус. Это отражается в UI как ⚠️, а не ❌.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from database.models import HousingType, Listing, Profile, RoommateGender

# Курс приблизительный (Kufar без ?cur=USD отдаёт цены в BYN, см. sources/kufar.py).
# Актуальный курс НБ РБ: https://www.nbrb.by/statistics/rates/ratesdaily
# Стоит обновлять вручную при заметных отклонениях от жизни.
BYN_TO_USD_RATE = 3.2

SUBLET_KEYWORDS = ("подсел", "койко-мест", "койко мест")
NOT_SUBLET_MARKERS = ("без подсел",)  # "без подселения" — отрицание, не сама подсказка
NO_PETS_KEYWORDS = ("без животных", "без домашних животных")
NO_SMOKING_KEYWORDS = ("без вредных привычек", "не курю", "некурящ")

FEMALE_KEYWORDS = ("девушк", "женщин", "девочк")
MALE_KEYWORDS = ("парн", "мужчин", "мужчине", "мужского пола")


@dataclass
class QuickProfile:
    """Облегчённый профиль для быстрого поиска (Version 1.1, п.E) — не
    сохраняется в БД, живёт только на время одной сессии поиска. Дублирует
    ИМЕНА полей настоящего Profile ровно настолько, насколько их использует
    matching.py — этого достаточно, чтобы работать с той же логикой без
    отдельной ветки кода."""

    max_budget: int
    preferred_roommate_gender: RoommateGender = RoommateGender.ANY
    housing_type: HousingType = HousingType.ANY
    pets: bool = False
    smoking: bool = False
    bad_habits: bool = False


@dataclass
class MatchExplanation:
    """Итог сопоставления, разложенный по критериям — чтобы честно
    показать пользователю, откуда взялся процент (Version 1.1, п.F/G)."""

    score: int
    budget_ok: bool
    district_ok: bool
    roommate_gender_ok: bool
    housing_type_ok: bool

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "budget_ok": self.budget_ok,
            "district_ok": self.district_ok,
            "roommate_gender_ok": self.roommate_gender_ok,
            "housing_type_ok": self.housing_type_ok,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MatchExplanation":
        return cls(
            score=data["score"],
            budget_ok=data["budget_ok"],
            district_ok=data["district_ok"],
            roommate_gender_ok=data["roommate_gender_ok"],
            housing_type_ok=data["housing_type_ok"],
        )


def price_to_usd(listing: Listing) -> float | None:
    if listing.price is None:
        return None
    if listing.currency == "USD":
        return float(listing.price)
    if listing.currency == "BYN":
        return listing.price / BYN_TO_USD_RATE
    return None  # неизвестная валюта — лучше не гадать


def match_listing(profile: Profile | QuickProfile, listing: Listing) -> bool:
    """Простой фильтр. По умолчанию — пропускаем (permissive), отсеиваем
    только то, что ТОЧНО не подходит: явно известная цена выше бюджета."""
    price_usd = price_to_usd(listing)
    if price_usd is not None and price_usd > profile.max_budget:
        return False
    return True


def explain_match(profile: Profile | QuickProfile, listing: Listing) -> MatchExplanation:
    """Веса — как в исходном ТЗ: бюджет+40, район+20, пол соседей+20,
    тип жилья+10, доп. предпочтения+10 (без отдельного флага в UI —
    слишком мелкий критерий, чтобы выносить его в чек-лист)."""
    text = f"{listing.title} {listing.description or ''}".lower()

    price_usd = price_to_usd(listing)
    budget_ok = price_usd is not None and price_usd <= profile.max_budget

    # Район уже гарантированно верный (см. докстринг модуля).
    district_ok = bool(listing.district)

    is_sublet = _is_sublet(text)
    is_apartment = listing.housing_type == "apartment"

    # "Пол соседей" — понятие, применимое только к комнате/подселению (там
    # реально ЖИВЁШЬ с кем-то). Для квартиры это не имеет смысла — там не
    # подселяются к соседям (см. правку в handlers/profile.py: при выборе
    # "Квартира" мы даже не задаём этот вопрос). Если считать его как обычно,
    # квартиры в поиске "неважно" систематически проигрывали бы в score —
    # в объявлениях о квартирах пол почти никогда не упоминается, и
    # эвристика честно возвращала бы False там, где вопрос попросту не
    # применим. Поэтому для квартир — всегда True (не штрафуем).
    if is_apartment or profile.preferred_roommate_gender == RoommateGender.ANY:
        roommate_gender_ok = True
    elif profile.preferred_roommate_gender == RoommateGender.FEMALE:
        roommate_gender_ok = _mentions(text, FEMALE_KEYWORDS)
    elif profile.preferred_roommate_gender == RoommateGender.MALE:
        roommate_gender_ok = _mentions(text, MALE_KEYWORDS)
    else:
        roommate_gender_ok = False

    if profile.housing_type == HousingType.ANY:
        housing_type_ok = True
    elif profile.housing_type == HousingType.APARTMENT:
        housing_type_ok = is_apartment  # достоверно — из какой категории Kufar пришло
    elif profile.housing_type == HousingType.SUBLET:
        housing_type_ok = not is_apartment and is_sublet
    else:  # ROOM
        housing_type_ok = not is_apartment and not is_sublet

    score = 0
    if budget_ok:
        score += 40
    if district_ok:
        score += 20
    if roommate_gender_ok:
        score += 20
    if housing_type_ok:
        score += 10

    extra = 0
    if not profile.pets and _mentions(text, NO_PETS_KEYWORDS):
        extra += 5
    if not profile.smoking and not profile.bad_habits and _mentions(text, NO_SMOKING_KEYWORDS):
        extra += 5
    score += min(extra, 10)

    return MatchExplanation(
        score=min(score, 100),
        budget_ok=budget_ok,
        district_ok=district_ok,
        roommate_gender_ok=roommate_gender_ok,
        housing_type_ok=housing_type_ok,
    )


def match_score(profile: Profile | QuickProfile, listing: Listing) -> int:
    """Тонкая обёртка над explain_match() для мест, которым нужно только
    число, без разбивки по критериям."""
    return explain_match(profile, listing).score


def _mentions(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_sublet(text: str) -> bool:
    if any(marker in text for marker in NOT_SUBLET_MARKERS):
        return False
    return _mentions(text, SUBLET_KEYWORDS)
