"""Промежуточная проверка парсера — без бота и без БД.

Запуск:
    python3 test_kufar_source.py

Печатает найденные объявления в консоль. Если что-то не так — пришли мне
вывод этого скрипта целиком (и текст ошибки, если он упадёт) — по нему
я поправлю регулярки в sources/kufar.py.
"""
import asyncio
import logging

from database.models import District
from sources.base import SearchParams
from sources.kufar import KufarSource

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


async def main() -> None:
    source = KufarSource()

    # Проверяем сразу на двух районах — если в одном из них слаг окажется
    # неверным, это будет видно по нулевому количеству объявлений оттуда.
    params = SearchParams(districts=[District.FRUNZENSKY, District.CENTRALNY])

    listings = await source.fetch(params)

    print(f"\nВсего найдено: {len(listings)}\n{'=' * 60}")
    for listing in listings[:10]:
        print(f"ID: {listing.external_id}")
        print(f"Район (запрошенный): {listing.district}")
        print(f"Цена: {listing.price} {listing.currency}" + (" (договорная)" if listing.is_negotiable else ""))
        print(f"Заголовок (черновой): {listing.title}")
        print(f"Ссылка: {listing.url}")
        print(f"Сырой текст карточки: {listing.description[:300]}")
        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
