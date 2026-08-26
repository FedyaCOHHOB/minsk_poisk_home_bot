from __future__ import annotations

from database.models import DISTRICT_LABELS, District, Listing
from services.matching import price_to_usd


def _district_label(district_value: str | None) -> str | None:
    if not district_value:
        return None
    try:
        return DISTRICT_LABELS[District(district_value)]
    except ValueError:
        return district_value  # не должно происходить, см. sources/kufar.py


def format_listing_card(
    listing: Listing,
    explanation: dict | None = None,
    position: tuple[int, int] | None = None,
) -> str:
    """explanation — словарь из MatchExplanation.to_dict() (services/matching.py).
    None — карточка без раздела score (например, в «Сохранённых»: там
    показывать процент соответствия к профилю, который мог с тех пор
    поменяться или вовсе не существовать при быстром поиске, не имеет
    смысла — см. handlers/search.py)."""
    price_usd = price_to_usd(listing)

    if listing.price is None:
        price_line = "💰 Договорная"
    elif price_usd is not None:
        price_line = f"💰 ${price_usd:.0f}/мес ({listing.price} {listing.currency})"
    else:
        price_line = f"💰 {listing.price} {listing.currency}/мес"

    district_line = f"📍 {_district_label(listing.district)}" if listing.district else ""

    title = (listing.title or "Комната в Минске").strip()
    description = (listing.description or "").strip()
    if len(description) > 300:
        description = description[:300].rsplit(" ", 1)[0] + "..."

    lines = []
    if position:
        current, total = position
        lines.append(f"📋 {current} из {total}")

    lines.append("🏠 " + title)
    lines.append(price_line)
    if district_line:
        lines.append(district_line)

    if explanation is not None:
        lines.append(f"\n⭐ Подходит вам: {explanation['score']}%")
        lines.append(_checklist_line(explanation) + "\n")
    else:
        lines.append("")

    if description:
        lines.append(description)

    return "\n".join(lines)


def _checklist_line(explanation: dict) -> str:
    items = [
        "✅ Бюджет" if explanation["budget_ok"] else "⚠️ Бюджет не указан",
        "✅ Район" if explanation["district_ok"] else "⚠️ Район не уточнён",
        "✅ Пол соседей" if explanation["roommate_gender_ok"] else "⚠️ Пол соседей не уточнён",
        "✅ Тип жилья" if explanation["housing_type_ok"] else "⚠️ Тип жилья не уточнён",
    ]
    return " · ".join(items)
