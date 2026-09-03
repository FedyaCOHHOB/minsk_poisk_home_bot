from datetime import timedelta

from database.models import Listing
from services.formatting import _freshness_label, format_listing_card
from utils.helpers import utcnow


def _listing(**overrides):
    defaults = dict(
        external_id="1", source="kufar", title="Улица А", description="Описание квартиры",
        price=300, currency="BYN", district="central", url="https://x/1",
        housing_type="room", parsed_at=utcnow(),
    )
    defaults.update(overrides)
    return Listing(**defaults)


class TestNoScoreDisplay:
    """По просьбе пользователя карточка больше не показывает "Подходит
    вам: X%" и чек-лист — сортировка по релевантности в поиске осталась
    (см. services/matching.py, handlers/search.py), но карточка это
    больше не выводит."""

    def test_no_percent_shown(self):
        listing = _listing()
        card = format_listing_card(listing)
        assert "%" not in card
        assert "Подходит вам" not in card

    def test_no_checklist_shown(self):
        listing = _listing()
        card = format_listing_card(listing)
        assert "Бюджет" not in card
        assert "Пол соседей" not in card
        assert "Тип жилья" not in card


class TestPositionIndicator:
    def test_shown_when_position_given(self):
        listing = _listing()
        card = format_listing_card(listing, position=(2, 7))
        assert "2 из 7" in card

    def test_hidden_when_position_not_given(self):
        listing = _listing()
        card = format_listing_card(listing)
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
        card = format_listing_card(listing)
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
        card = format_listing_card(listing)
        assert card.count("Улица А") == 1

    def test_description_shown_below_header(self):
        listing = _listing(title="Улица А", description="Совсем другой текст")
        card = format_listing_card(listing)
        assert "Совсем другой текст" in card
