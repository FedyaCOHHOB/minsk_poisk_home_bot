"""Оркестрация: сходить к источнику(ам) объявлений, сохранить в БД,
вернуть уже ORM-объекты Listing. Пока источник один (Kufar), но
handlers не должны об этом знать — только этот сервис."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from database import crud
from database.models import District, HousingType, Listing
from sources.base import SearchParams
from sources.kufar import KufarSource, categories_for_housing_type

logger = logging.getLogger(__name__)


async def search_and_store(
    session: AsyncSession,
    districts: list[District],
    housing_type: HousingType = HousingType.ANY,
) -> list[Listing]:
    source = KufarSource()
    categories = categories_for_housing_type(housing_type)
    raw_listings = await source.fetch(SearchParams(districts=districts, categories=categories))

    listings: list[Listing] = []
    for raw in raw_listings:
        listing = await crud.upsert_listing(session, raw)
        listings.append(listing)

    logger.info("search_and_store: получено %s объявлений от %s", len(listings), source.name)
    return listings


# Все официальные районы, кроме "любой" — для полного админского обновления базы.
ALL_REAL_DISTRICTS = [d for d in District if d != District.ANY]


async def update_all_listings(session: AsyncSession) -> int:
    """Для /update — прогоняет по всем районам и обеим категориям (комнаты
    и квартиры) сразу, чтобы база была свежей ещё до того, как конкретный
    пользователь запустит поиск."""
    listings = await search_and_store(session, ALL_REAL_DISTRICTS, housing_type=HousingType.ANY)
    return len(listings)
