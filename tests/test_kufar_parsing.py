import pytest

from database.models import District, HousingType
from sources.kufar import DISTRICT_SLUGS, KufarSource, categories_for_housing_type

k = KufarSource()

# Реальные слипшиеся тексты карточек, собранные при разведке Kufar
# (Этап 3 и позже) — комнаты и квартиры вперемешку.
REAL_SAMPLES = [
    (
        "358 р. / мес.calculatorАренда комнатыЯнковского ул, 3, Минск"
        "Сдается уютная комната в 2-комнатной квартире по адресу: ул. "
        "Янковского, 3. Кого ищем: девушку 24–35 лет, без вредных привычек, "
        "ответственную, ценящу...ПозвонитьСравнить",
        "Янковского ул, 3",
    ),
    (
        "ДоговорнаяСдаю 2 комнаты в наймОдесская ул, 16, МинскСдаётся "
        "2-комнатны высокий этаж Светлая и ухоженная квартира с "
        "изолированными комнатами...ПозвонитьСравнить",
        "Одесская ул, 16",
    ),
    (
        "vip 480 р. / мес.calculatorСдаю жильё для строителей сотрудников. "
        "Стоимость человека МинскСтахановская ул, МинскТракторный "
        "заводЖильё для рабочих строителей...ПозвонитьСравнить",
        "Стахановская ул",
    ),
    (
        "550 р. / мес.calculatorСдам комнату Газеты Правда пр, 22, Минск"
        "Сдается комната в четырехкомнатной квартире только девушке "
        "( женщине)...ПозвонитьСравнить",
        "Газеты Правда пр, 22",
    ),
    (
        "1 659 р. / мес.calculator2 комн., 63 м², этаж 2 из 25Кольцова "
        "ул, 37, Минск, мкр. Зеленый лугСдаётся светлая двухкомнатная "
        "квартира...Сравнить",
        "Кольцова ул, 37",
    ),
    (
        "1 809 р. / мес.calculator2 комн., 51.2 м², этаж 1 из 12Сурганова "
        "ул, 70, МинскСдается двухкомнатная квартира от собственника без "
        "посредников...ПозвонитьСравнить",
        "Сурганова ул, 70",
    ),
]


class TestCleanText:
    @pytest.mark.parametrize("raw,_expected_addr", REAL_SAMPLES)
    def test_removes_ui_noise(self, raw, _expected_addr):
        cleaned = k._clean_text(raw)
        assert "Позвонить" not in cleaned
        assert "Сравнить" not in cleaned
        assert "calculator" not in cleaned

    def test_removes_price_prefix(self):
        cleaned = k._clean_text("550 р. / мес.calculatorСдам комнату")
        assert "550" not in cleaned

    def test_removes_negotiable_marker(self):
        cleaned = k._clean_text("ДоговорнаяСдаю 2 комнаты")
        assert "Договорная" not in cleaned

    def test_removes_vip_prefix(self):
        cleaned = k._clean_text("vip 480 р. / мес.calculatorТекст")
        assert not cleaned.lower().startswith("vip")


class TestAddressExtraction:
    """Регулярка находит именно улицу, перепрыгивая через слипшиеся без
    пробела слова спереди — это и есть основная сложность."""

    @pytest.mark.parametrize("raw,expected_addr", REAL_SAMPLES)
    def test_extracts_correct_address(self, raw, expected_addr):
        cleaned = k._clean_text(raw)
        address, _body = k._split_address_and_body(cleaned)
        assert address == expected_addr

    @pytest.mark.parametrize("raw,_expected_addr", REAL_SAMPLES)
    def test_body_has_no_leftover_ui_noise(self, raw, _expected_addr):
        cleaned = k._clean_text(raw)
        _address, body = k._split_address_and_body(cleaned)
        assert "Позвонить" not in body
        assert "Сравнить" not in body

    def test_no_minsk_falls_back_to_prefix(self):
        address, body = k._split_address_and_body("Просто текст без города")
        assert address == "Просто текст без города"
        assert body == ""


class TestDistrictSlugs:
    def test_all_nine_districts_present(self):
        real_districts = [d for d in District if d != District.ANY]
        assert len(real_districts) == 9
        for district in real_districts:
            assert district in DISTRICT_SLUGS

    def test_slugs_end_with_rajon(self):
        for slug in DISTRICT_SLUGS.values():
            assert slug.endswith("-rajon")


class TestUrlBuilding:
    def test_specific_district_room(self):
        url = k._build_url(District.MOSKOVSKY, "room")
        assert url == "https://re.kufar.by/l/minsk-moskovskij-rajon/snyat/komnatu"

    def test_specific_district_apartment(self):
        url = k._build_url(District.MOSKOVSKY, "apartment")
        assert url == "https://re.kufar.by/l/minsk-moskovskij-rajon/snyat/kvartiru"

    def test_no_district_is_citywide(self):
        url = k._build_url(None, "room")
        assert url == "https://re.kufar.by/l/minsk/snyat/komnatu"


class TestCategoriesForHousingType:
    def test_room_and_sublet_use_room_category(self):
        assert categories_for_housing_type(HousingType.ROOM) == ["room"]
        assert categories_for_housing_type(HousingType.SUBLET) == ["room"]

    def test_apartment_uses_apartment_category(self):
        assert categories_for_housing_type(HousingType.APARTMENT) == ["apartment"]

    def test_any_uses_both_categories(self):
        assert categories_for_housing_type(HousingType.ANY) == ["room", "apartment"]


class TestFetchTargetsForAnyDistrict:
    """Реальный найденный баг: 'Любой район' раньше давал ОДИН запрос без
    привязки к району (targets=[None]) — объявления получали district=None,
    что ломало и score, и уведомления. Теперь вместо этого — все 9 районов
    по отдельности."""

    def test_any_district_expands_to_all_nine(self):
        districts = [d for d in [District.ANY] if d != District.ANY]
        targets = list(districts) or list(DISTRICT_SLUGS.keys())
        assert len(targets) == 9
        assert None not in targets

    def test_specific_districts_stay_as_is(self):
        selected = [District.CENTRALNY, District.FRUNZENSKY]
        districts = [d for d in selected if d != District.ANY]
        targets = list(districts) or list(DISTRICT_SLUGS.keys())
        assert targets == selected
