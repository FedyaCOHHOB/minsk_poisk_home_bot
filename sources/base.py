"""Абстракция источника объявлений. Kufar — первая и пока единственная
реализация (KufarSource в kufar.py). Если понадобится другой сайт или
собственные объявления пользователей — добавляется новый класс с этим же
интерфейсом, остальной код (services/listings.py, бот) не меняется."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from database.models import District
from sources.schemas import RawListing


@dataclass
class SearchParams:
    # Пустой список или [District.ANY] = без ограничения по району.
    districts: list[District] = field(default_factory=list)
    # Категории Kufar для запроса: "komnatu" и/или "kvartiru".
    # Заполняется через sources.kufar.categories_for_housing_type().
    categories: list[str] = field(default_factory=lambda: ["komnatu"])


class BaseListingSource(ABC):
    name: str

    @abstractmethod
    async def fetch(self, params: SearchParams) -> list[RawListing]:
        """Возвращает список найденных объявлений. Не должно бросать
        исключение наружу при сбое одного запроса — источник сам решает,
        логировать и возвращать частичный результат, либо пустой список."""
        ...
