from datetime import datetime

import pytest

from services.notifications import MINSK_TZ, _is_quiet_hours, _plural_variants


class TestQuietHours:
    """Тихие часы 23:00–08:00 по Минску — переход через полночь самое
    простое место, чтобы ошибиться в такой логике."""

    @pytest.mark.parametrize(
        "hour,minute,expected",
        [
            (22, 59, False),
            (23, 0, True),
            (23, 59, True),
            (0, 0, True),
            (3, 0, True),
            (7, 59, True),
            (8, 0, False),
            (8, 1, False),
            (12, 0, False),
            (22, 0, False),
        ],
    )
    def test_boundaries(self, hour, minute, expected):
        now = datetime(2026, 1, 15, hour, minute, tzinfo=MINSK_TZ)
        assert _is_quiet_hours(now) is expected


class TestPluralVariants:
    @pytest.mark.parametrize(
        "count,expected",
        [
            (1, "новый вариант"),
            (2, "новых варианта"),
            (3, "новых варианта"),
            (4, "новых варианта"),
            (5, "новых вариантов"),
            (11, "новых вариантов"),
            (12, "новых вариантов"),
            (21, "новый вариант"),
            (22, "новых варианта"),
            (25, "новых вариантов"),
            (100, "новых вариантов"),
            (101, "новый вариант"),
        ],
    )
    def test_russian_pluralization(self, count, expected):
        assert _plural_variants(count) == expected
