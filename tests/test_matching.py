from database.models import HousingType, Listing, RoommateGender
from services.matching import (
    QuickProfile,
    _is_sublet,
    explain_match,
    match_listing,
    price_to_usd,
)


def _listing(**overrides):
    defaults = dict(
        external_id="1", source="kufar", title="Тест", description="",
        price=300, currency="BYN", district="central", url="https://x/1",
        housing_type="room",
    )
    defaults.update(overrides)
    return Listing(**defaults)


class TestPriceConversion:
    def test_byn_converts_to_usd(self):
        listing = _listing(price=320, currency="BYN")
        assert price_to_usd(listing) == 100.0  # 320 / 3.2

    def test_usd_passthrough(self):
        listing = _listing(price=100, currency="USD")
        assert price_to_usd(listing) == 100.0

    def test_no_price_returns_none(self):
        listing = _listing(price=None)
        assert price_to_usd(listing) is None

    def test_unknown_currency_returns_none(self):
        listing = _listing(price=100, currency="EUR")
        assert price_to_usd(listing) is None


class TestHardFilter:
    def test_within_budget_passes(self):
        profile = QuickProfile(max_budget=150)
        listing = _listing(price=320, currency="BYN")  # ~$100
        assert match_listing(profile, listing) is True

    def test_over_budget_rejected(self):
        profile = QuickProfile(max_budget=50)
        listing = _listing(price=320, currency="BYN")  # ~$100
        assert match_listing(profile, listing) is False

    def test_negotiable_price_not_hard_rejected(self):
        """Договорная цена (price=None) — неопределённость, не повод
        отбрасывать объявление жёстким фильтром."""
        profile = QuickProfile(max_budget=50)
        listing = _listing(price=None)
        assert match_listing(profile, listing) is True


class TestSubletDetection:
    """_is_sublet — источник реального бага: 'без подселения' раньше
    засчитывалось как 'есть подселение' из-за поиска по голой подстроке."""

    def test_detects_sublet(self):
        assert _is_sublet("подселение для девушки") is True

    def test_detects_koyko_mesto(self):
        assert _is_sublet("койко-место для мужчин") is True

    def test_negation_not_counted_as_sublet(self):
        assert _is_sublet("без подселения, вся комната ваша") is False

    def test_no_mention_is_false(self):
        assert _is_sublet("просторная светлая комната") is False


class TestHousingTypeMatching:
    """Комбинации: комната / подселение / квартира — квартира определяется
    достоверно (по категории Kufar), комната/подселение — эвристикой."""

    def test_apartment_profile_wants_apartment_listing(self):
        profile = QuickProfile(max_budget=1000, housing_type=HousingType.APARTMENT)
        apartment = _listing(housing_type="apartment", description="просторная квартира")
        assert explain_match(profile, apartment).housing_type_ok is True

    def test_apartment_profile_rejects_room(self):
        profile = QuickProfile(max_budget=1000, housing_type=HousingType.APARTMENT)
        room = _listing(housing_type="room", description="уютная комната")
        assert explain_match(profile, room).housing_type_ok is False

    def test_room_profile_accepts_room_without_sublet_mention(self):
        profile = QuickProfile(max_budget=1000, housing_type=HousingType.ROOM)
        room = _listing(housing_type="room", description="уютная комната, без подселения")
        assert explain_match(profile, room).housing_type_ok is True

    def test_room_profile_rejects_sublet(self):
        profile = QuickProfile(max_budget=1000, housing_type=HousingType.ROOM)
        sublet = _listing(housing_type="room", description="подселение, койко-место")
        assert explain_match(profile, sublet).housing_type_ok is False

    def test_room_profile_rejects_apartment(self):
        profile = QuickProfile(max_budget=1000, housing_type=HousingType.ROOM)
        apartment = _listing(housing_type="apartment", description="просторная квартира")
        assert explain_match(profile, apartment).housing_type_ok is False

    def test_sublet_profile_accepts_sublet(self):
        profile = QuickProfile(max_budget=1000, housing_type=HousingType.SUBLET)
        sublet = _listing(housing_type="room", description="подселение к девушке")
        assert explain_match(profile, sublet).housing_type_ok is True

    def test_any_profile_accepts_everything(self):
        profile = QuickProfile(max_budget=1000, housing_type=HousingType.ANY)
        for housing_type, desc in [("room", "комната"), ("apartment", "квартира")]:
            listing = _listing(housing_type=housing_type, description=desc)
            assert explain_match(profile, listing).housing_type_ok is True


class TestRoommateGenderForApartments:
    """Реальный найденный баг: квартиры несправедливо теряли очки за
    'пол соседей', хотя для квартиры это понятие неприменимо (там не
    подселяются к соседям)."""

    def test_apartment_never_penalized_for_roommate_gender(self):
        profile = QuickProfile(
            max_budget=1000,
            housing_type=HousingType.ANY,
            preferred_roommate_gender=RoommateGender.FEMALE,
        )
        apartment = _listing(housing_type="apartment", description="квартира с ремонтом")
        assert explain_match(profile, apartment).roommate_gender_ok is True

    def test_room_still_uses_heuristic(self):
        profile = QuickProfile(
            max_budget=1000,
            housing_type=HousingType.ANY,
            preferred_roommate_gender=RoommateGender.FEMALE,
        )
        room_no_mention = _listing(housing_type="room", description="сдаётся комната")
        room_for_female = _listing(housing_type="room", description="комната для девушки")
        assert explain_match(profile, room_no_mention).roommate_gender_ok is False
        assert explain_match(profile, room_for_female).roommate_gender_ok is True

    def test_any_gender_preference_always_ok(self):
        profile = QuickProfile(max_budget=1000, preferred_roommate_gender=RoommateGender.ANY)
        room = _listing(housing_type="room", description="сдаётся комната")
        assert explain_match(profile, room).roommate_gender_ok is True


class TestScoreCap:
    def test_score_never_exceeds_100(self):
        profile = QuickProfile(
            max_budget=1000, housing_type=HousingType.ANY,
            preferred_roommate_gender=RoommateGender.ANY,
        )
        listing = _listing(
            price=100, currency="USD",
            description="идеальный вариант без животных без вредных привычек",
        )
        assert explain_match(profile, listing).score <= 100
