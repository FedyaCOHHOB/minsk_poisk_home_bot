from datetime import timedelta

from database.models import Listing
from services.formatting import _freshness_label, format_listing_card
from services.matching import MatchExplanation
from utils.helpers import utcnow


def _listing(**overrides):
    defaults = dict(
        external_id="1", source="kufar", title="Улица А", description="Описание квартиры",
        price=300, currency="BYN", district="central", url="https://x/1",
        housing_type="room", parsed_at=utcnow(),
    )
    defaults.update(overrides)
    return Listing(**defaults)


class TestScoreSection:
    def test_shown_when_explanation_given(self):
        listing = _listing()
        explanation = MatchExplanation(
            score=90, budget_ok=True, district_ok=True,
            roommate_gender_ok=True, housing_type_ok=True,
        )
        card = format_listing_card(listing, explanation.to_dict())
        assert "90%" in card
        assert "✅ Бюджет" in card

    def test_hidden_when_explanation_is_none(self):
        """Карточка в 'Сохранённых' — без score, там это неуместно."""
        listing = _listing()
        card = format_listing_card(listing, None)
        assert "Подходит вам" not in card
        assert "%" not in card


class TestChecklistHidesInapplicableCriteria:
    def test_apartment_hides_roommate_gender_line(self):
        listing = _listing(housing_type="apartment")
        explanation = MatchExplanation(
            score=90, budget_ok=True, district_ok=True,
            roommate_gender_ok=True, housing_type_ok=True,
        )
        card = format_listing_card(listing, explanation.to_dict())
        assert "Пол соседей" not in card

    def test_room_shows_roommate_gender_line(self):
        listing = _listing(housing_type="room")
        explanation = MatchExplanation(
            score=70, budget_ok=True, district_ok=True,
            roommate_gender_ok=False, housing_type_ok=True,
        )
        card = format_listing_card(listing, explanation.to_dict())
        assert "Пол соседей" in card
        assert "⚠️ Пол соседей не уточнён" in card


class TestPositionIndicator:
    def test_shown_when_position_given(self):
        listing = _listing()
        card = format_listing_card(listing, None, position=(2, 7))
        assert "2 из 7" in card

    def test_hidden_when_position_not_given(self):
        listing = _listing()
        card = format_listing_card(listing, None)
        assert "из" not in card.split("\n")[0]


class TestFreshnessLabel:
    def test_just_now(self):
        assert _freshness_label(utcnow() - timedelta(minutes=5)) == "меньше часа назад"

    def test_hours_ago(self):
        assert _freshness_label(utcnow() - timedelta(hours=3)) == "3 ч назад"

    def test_yesterday(self):
        assert _freshness_label(utcnow() - timedelta(days=1, hours=1)) == "вчера"

    def test_days_ago(self):
        assert _freshness_label(utcnow() - timedelta(days=4)) == "4 дн назад"

    def test_older_falls_back_to_date(self):
        old = utcnow() - timedelta(days=30)
        label = _freshness_label(old)
        assert label == old.strftime("%d.%m.%Y")

    def test_appears_in_card(self):
        listing = _listing(parsed_at=utcnow() - timedelta(hours=2))
        card = format_listing_card(listing, None)
        assert "Заметили у себя" in card
        assert "2 ч назад" in card


class TestTitleAndDescriptionRenderedAsGiven:
    """Раньше дедупликация title/description жила в самом format_listing_card
    (обрезала совпадающий префикс) — теперь она не нужна: sources/kufar.py
    (_split_address_and_body) гарантирует их неперекрытие ещё на этапе
    разбора, раньше, чем данные вообще попадают сюда (см. test_kufar_parsing.py
    ::TestAddressExtraction). Formatting просто честно рендерит то, что
    получил — эта гарантия здесь просто фиксируется как контракт."""

    def test_title_appears_once_in_header(self):
        listing = _listing(title="Улица А", description="Другой текст описания")
        card = format_listing_card(listing, None)
        assert card.count("Улица А") == 1

    def test_description_shown_below_header(self):
        listing = _listing(title="Улица А", description="Совсем другой текст")
        card = format_listing_card(listing, None)
        assert "Совсем другой текст" in card
