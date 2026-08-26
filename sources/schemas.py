"""DTO для «сырых» данных, которые источник (например, Kufar) успел
извлечь. Специально отделён от ORM-модели Listing: если Kufar поменяет
разметку, ломается маппинг в одном месте, а не вся модель БД."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RawListing:
    external_id: str
    source: str

    title: str
    description: str | None
    price: int | None          # None, если цена договорная / не распозналась
    currency: str               # "BYN" или "USD"
    is_negotiable: bool

    url: str

    # Район мы знаем заранее — сами выбрали, по какому URL идти (см. kufar.py),
    # поэтому это не «угадано» эвристикой, а достоверно.
    district: str | None = None
    image_url: str | None = None
