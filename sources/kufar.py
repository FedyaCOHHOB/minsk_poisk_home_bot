"""Источник объявлений — Kufar (re.kufar.by), категории «Комнаты» и
«Квартиры» в Минске.

ВАЖНЫЕ ВЫВОДЫ РАЗВЕДКИ (Этап 3 + добавление квартир), на которых строится
этот модуль:

1. Страницы `re.kufar.by/l/minsk/snyat/komnatu` и `.../snyat/kvartiru`
   отдают готовый HTML с данными объявлений без выполнения JS — простого
   GET-запроса достаточно, headless-браузер не нужен. Разметка карточек
   идентична в обеих категориях (проверено).
2. `robots.txt` разрешает «чистые» canonical-адреса без query-параметров,
   но запрещает URL с `?...` (проверено на нескольких примерах в обеих
   категориях). Поэтому этот модуль СОЗНАТЕЛЬНО не использует
   query-параметры вообще: ни `?cur=USD`, ни курсорную пагинацию. Берём
   первую страницу выдачи (~30 объявлений) по каждому запрошенному
   району и каждой запрошенной категории.
3. У Kufar уже есть готовая фильтрация по официальным районам Минска прямо
   в пути: `/l/minsk-<slug>-rajon/snyat/<категория>`. Все 9 слагов из
   DISTRICT_SLUGS подтверждены напрямую со страницы фильтров Kufar (была
   отдельная проверка помимо изначальной разведки — раньше часть слагов
   были только предположением по паттерну транслитерации).
4. Без `?cur=USD` цена приходит в белорусских рублях (BYN), не в USD.
   Конвертация для сравнения с бюджетом анкеты (он в USD) — забота
   matching.py, а не этого модуля: тут мы просто честно сохраняем то,
   что видим, с пометкой валюты.
5. Комнаты и подселение — НЕ разные категории на Kufar, оба типа приходят
   вперемешку под /snyat/komnatu. Различать их — задача текстовой
   эвристики в matching.py. А вот квартиры — это ДЕЙСТВИТЕЛЬНО отдельная
   категория (/snyat/kvartiru) с отдельным URL, поэтому здесь это не
   эвристика, а достоверный факт: из какой категории пришло объявление,
   в такую и попало поле RawListing.housing_type ("room"/"apartment").

ЧТО ТОЧНО ПОТРЕБУЕТ ДОРАБОТКИ:
Извлечение title/description всё ещё идёт из «слипшегося» текста
ссылки-карточки эвристиками (см. _clean_text, _split_address_and_body).
Адрес извлекается неплохо (проверено на реальных примерах), но это
по-прежнему не парсинг настоящей DOM-структуры, а разбор текстового
блока — при существенном изменении вёрстки Kufar может потребовать правок.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup

from database.models import District, HousingType
from sources.base import BaseListingSource, SearchParams
from sources.schemas import RawListing

logger = logging.getLogger(__name__)

BASE_HOST = "https://re.kufar.by"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Все 9 подтверждены напрямую со страницы фильтров Kufar (блок "Район" на
# /l/minsk/snyat/kvartiru), не только по паттерну транслитерации.
DISTRICT_SLUGS: dict[District, str] = {
    District.CENTRALNY: "centralnyj-rajon",
    District.FRUNZENSKY: "frunzenskij-rajon",
    District.MOSKOVSKY: "moskovskij-rajon",
    District.OKTYABRSKY: "oktyabrskij-rajon",
    District.LENINSKY: "leninskij-rajon",
    District.ZAVODSKOY: "zavodskoj-rajon",
    District.PERVOMAYSKY: "pervomajskij-rajon",
    District.SOVETSKY: "sovetskij-rajon",
    District.PARTIZANSKY: "partizanskij-rajon",
}

# Категории Kufar — путь после /snyat/. "room" — общее имя для нашей
# ROOM/SUBLET (Kufar их не различает), "apartment" — для kvartiru.
CATEGORY_PATHS: dict[str, str] = {
    "room": "komnatu",
    "apartment": "kvartiru",
}


def categories_for_housing_type(housing_type: HousingType) -> list[str]:
    """Какие категории Kufar запрашивать для данного предпочтения жилья.
    ANY — обе категории (двойной набор запросов, но по-прежнему один
    запрос на район на категорию, в рамках допустимого robots.txt)."""
    if housing_type == HousingType.APARTMENT:
        return ["apartment"]
    if housing_type == HousingType.ANY:
        return ["room", "apartment"]
    return ["room"]  # ROOM, SUBLET — одна и та же категория Kufar


# /vi/minsk/snyat/komnatu-dolgosrochno/1-k/1082235025?block_name=... → id в конце пути
LISTING_HREF_RE = re.compile(r"/vi/[^\"'?]+?/(\d+)(?:\?|$)")
PRICE_RE = re.compile(r"([\d\s\xa0]+)\s*р\.\s*/\s*мес")
NEGOTIABLE_MARKER = "Договорная"
TRAILING_NOISE_RE = re.compile(r"(Позвонить)?Сравнить\s*$")
CALC_WORD_RE = re.compile(r"calculator", re.IGNORECASE)

# Пытается найти именно улицу (а не всю слипшуюся шапку целиком) — ищем по
# маркеру типа "ул"/"пр"/"пер" и т.п., а не по границам пробелов: в слипшемся
# тексте карточки (см. _clean_text) пробелы между сегментами не всегда на
# месте, зато граница по типу улицы находится надёжно в любом случае —
# регулярка сама "перепрыгивает" через приклеенные спереди слова, находя
# начало с заглавной буквы прямо перед маркером.
_STREET_TYPES = r"ул|пр-т|просп|пер|б-р|бул|пл|наб|тракт|пр"
STREET_RE = re.compile(
    rf"([А-ЯЁ][а-яё\-]*(?:\s[А-ЯЁ][а-яё\-]*)*\s(?:{_STREET_TYPES})\.?,?\s*\d*[а-я]?)"
)


class KufarSource(BaseListingSource):
    name = "kufar"

    def __init__(self, request_delay: float = 1.0, timeout: float = 10.0):
        self.request_delay = request_delay
        self.timeout = timeout

    def _build_url(self, district: District | None, category: str) -> str:
        slug = DISTRICT_SLUGS.get(district) if district else None
        path = f"/l/minsk-{slug}" if slug else "/l/minsk"
        category_path = CATEGORY_PATHS[category]
        return f"{BASE_HOST}{path}/snyat/{category_path}"

    async def fetch(self, params: SearchParams) -> list[RawListing]:
        districts = [d for d in params.districts if d != District.ANY]
        # "Любой район" — раньше здесь был ОДИН запрос по всему городу без
        # привязки к району (targets=[None]), из-за чего такие объявления
        # получали district=None. Это ломало сразу две вещи: district_ok в
        # score всегда был False (см. services/matching.py), и уведомления
        # никогда не находили совпадений, потому что искали Listing.district
        # == "any" — а такого значения не бывает физически. Теперь вместо
        # одного нерасличимого запроса — по одному на каждый настоящий район
        # (тот же список, что использует /update у админа), чтобы у всех
        # объявлений всегда был настоящий, а не пустой район.
        targets: list[District | None] = list(districts) or list(DISTRICT_SLUGS.keys())
        categories = params.categories or ["room"]

        # Дедуп на случай, если один и тот же listing попал в выдачу
        # нескольких районов (маловероятно, но не бесплатно проверить).
        collected: dict[str, RawListing] = {}

        request_pairs = [(d, c) for d in targets for c in categories]

        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS, timeout=self.timeout
        ) as client:
            for i, (district, category) in enumerate(request_pairs):
                if i > 0:
                    await asyncio.sleep(self.request_delay)

                url = self._build_url(district, category)
                html = await self._get_with_retry(client, url)
                if html is None:
                    logger.warning("Не удалось получить %s, пропускаю", url)
                    continue

                district_label = district.value if district else None
                for listing in self._parse_html(html, district_label, category):
                    collected[listing.external_id] = listing

        logger.info(
            "Kufar: собрано %s объявлений (%s запросов, категории: %s)",
            len(collected), len(request_pairs), categories,
        )
        return list(collected.values())

    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, attempts: int = 3
    ) -> str | None:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.text
                logger.warning(
                    "Kufar ответил %s для %s (попытка %s/%s)",
                    response.status_code, url, attempt, attempts,
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "Ошибка запроса к Kufar %s (попытка %s/%s): %s",
                    url, attempt, attempts, exc,
                )
            if attempt < attempts:
                await asyncio.sleep(2 ** attempt)  # 2s, 4s
        return None

    def _parse_html(
        self, html: str, district_label: str | None, category: str
    ) -> list[RawListing]:
        soup = BeautifulSoup(html, "lxml")
        listings: list[RawListing] = []
        seen_ids: set[str] = set()

        for a in soup.find_all("a", href=True):
            match = LISTING_HREF_RE.search(a["href"])
            if not match:
                continue

            external_id = match.group(1)
            if external_id in seen_ids:
                continue  # тот же listing уже встретился (например, VIP-повтор)
            seen_ids.add(external_id)

            text = a.get_text(" ", strip=True)
            if not text:
                continue

            price, currency, is_negotiable = self._extract_price(text)
            cleaned = self._clean_text(text)
            address, body = self._split_address_and_body(cleaned)
            image_url = self._extract_image(a)

            listings.append(
                RawListing(
                    external_id=external_id,
                    source=self.name,
                    title=address,
                    description=body,
                    price=price,
                    currency=currency,
                    is_negotiable=is_negotiable,
                    url=self._absolute_url(a["href"]),
                    district=district_label,
                    image_url=image_url,
                    housing_type=category,  # "room" | "apartment" — достоверно
                )
            )

        return listings

    @staticmethod
    def _extract_price(text: str) -> tuple[int | None, str, bool]:
        if NEGOTIABLE_MARKER in text:
            return None, "BYN", True
        match = PRICE_RE.search(text)
        if not match:
            return None, "BYN", False
        digits = re.sub(r"[\s\xa0]", "", match.group(1))
        if digits.isdigit():
            return int(digits), "BYN", False
        return None, "BYN", False

    @staticmethod
    def _clean_text(text: str) -> str:
        """Убирает цену/vip-метку/служебные слова из слипшегося текста карточки.
        Это единая точка очистки — и title, и description строятся из
        результата этой функции, чтобы не расходились между собой."""
        cleaned = text
        if cleaned.lower().startswith("vip"):
            cleaned = cleaned[3:]
        cleaned = PRICE_RE.sub("", cleaned)
        cleaned = cleaned.replace(NEGOTIABLE_MARKER, "")
        cleaned = CALC_WORD_RE.sub("", cleaned)
        cleaned = TRAILING_NOISE_RE.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
        return cleaned

    @staticmethod
    def _split_address_and_body(cleaned: str) -> tuple[str, str]:
        """Возвращает (адрес_для_шапки, тело_описания).

        Сначала пробуем найти именно улицу через STREET_RE — это надёжнее
        угадывания по пробелам. Если не нашлась (нестандартный формат
        адреса) — используем всё, что идёт до ПОСЛЕДНЕГО "Минск" в тексте:
        эмпирически это почти всегда граница между шапкой (действие+адрес,
        иногда ещё и район/метро) и настоящим описанием. Последнее, а не
        первое вхождение — потому что у части объявлений "Минск" встречается
        дважды (отдельно для улицы и отдельно для района/метро)."""
        boundary = cleaned.rfind("Минск")
        if boundary == -1:
            return cleaned[:100], ""

        head = cleaned[: boundary + len("Минск")]
        body = cleaned[boundary + len("Минск"):].strip(" ,.")

        street_match = STREET_RE.search(head)
        address = street_match.group(1).strip(" ,") if street_match else head.strip(" ,")

        return address, body

    @staticmethod
    def _extract_image(anchor) -> str | None:
        img = anchor.find("img")
        if img is None:
            return None
        src = img.get("src") or img.get("data-src")
        if not src:
            return None
        return src if src.startswith("http") else f"{BASE_HOST}{src}"

    @staticmethod
    def _absolute_url(href: str) -> str:
        return href if href.startswith("http") else f"{BASE_HOST}{href}"

