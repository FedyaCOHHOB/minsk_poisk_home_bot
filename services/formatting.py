from __future__ import annotations

from database.models import DISTRICT_LABELS, District, Listing
from services.matching import price_to_usd
from utils.helpers import utcnow


def _district_label(district_value: str | None) -> str | None:
    if not district_value:
        return None
    try:
        return DISTRICT_LABELS[District(district_value)]
    except ValueError:
        return district_value  # не должно происходить, см. sources/kufar.py


def _freshness_label(parsed_at) -> str:
    """Честная формулировка: это МЫ впервые увидели объявление в это время,
    не обязательно момент публикации на Kufar (его достоверно вытащить не
    удалось — см. README). Для объявлений, которые регулярно подтягиваются
    поиском/уведомлениями, это всё равно неплохой прокси свежести."""
    delta = utcnow() - parsed_at
    if delta.days == 0:
        if delta.seconds < 3600:
            return "меньше часа назад"
        hours = delta.seconds // 3600
        return f"{hours} ч назад"
    if delta.days == 1:
        return "вчера"
    if delta.days < 7:
        return f"{delta.days} дн назад"
    return parsed_at.strftime("%d.%m.%Y")


def format_listing_card(
    listing: Listing,
    position: tuple[int, int] | None = None,
) -> str:
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
    if listing.parsed_at:
        lines.append(f"🕐 Заметили у себя: {_freshness_label(listing.parsed_at)}")

    lines.append("")
    if description:
        lines.append(description)

    return "\n".join(lines)
