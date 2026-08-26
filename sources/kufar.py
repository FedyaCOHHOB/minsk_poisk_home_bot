"""Источник объявлений — Kufar (re.kufar.by), категория «Комнаты» в Минске.

ВАЖНЫЕ ВЫВОДЫ РАЗВЕДКИ (Этап 3), на которых строится этот модуль:

1. Страница `re.kufar.by/l/minsk/snyat/komnatu` отдаёт готовый HTML с данными
   объявлений без выполнения JS — простого GET-запроса достаточно,
   headless-браузер не нужен.
2. `robots.txt` разрешает «чистые» canonical-адреса без query-параметров,
   но запрещает URL с `?...` (проверено на двух разных примерах). Поэтому
   этот модуль СОЗНАТЕЛЬНО не использует query-параметры вообще: ни
   `?cur=USD`, ни курсорную пагинацию. Берём первую страницу выдачи
   (~30 объявлений) по каждому запрошенному району.
3. У Kufar уже есть готовая фильтрация по официальным районам Минска прямо
   в пути: `/l/minsk-<slug>-rajon/snyat/komnatu`. Слаги centralnyj-rajon,
   frunzenskij-rajon, sovetskij-rajon, oktyabrskij-rajon подтверждены
   вручную. Остальные — по устойчивому паттерну транслитерации, не
   проверены поштучно (см. DISTRICT_SLUGS ниже).
4. Без `?cur=USD` цена приходит в белорусских рублях (BYN), не в USD.
   Конвертация для сравнения с бюджетом анкеты (он в USD) — забота
   matching.py, а не этого модуля: тут мы просто честно сохраняем то,
   что видим, с пометкой валюты.
5. Kufar не делит объявления на «комната» и «подселение» как отдельные
   категории — оба типа приходят вперемешку под /snyat/komnatu. Различать
   их — задача текстовой эвристики в matching.py, не этого модуля.

ЧТО ТОЧНО ПОТРЕБУЕТ ДОРАБОТКИ:
Извлечение полей сейчас идёт из «слипшегося» текста ссылки-карточки
(вся карточка — один <a>, внутри — заголовок, цена, адрес, описание без
явных разделителей). Это рабочий черновик первого прохода, а не
финальная версия — как только реальный вывод скрипта будет перед глазами
(test_kufar_source.py), регулярки на title/address почти наверняка
потребуется подправить под то, что видно на самом деле.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup

from database.models import District
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

# Проверены вручную: CENTRALNY, FRUNZENSKY, SOVETSKY, OKTYABRSKY.
# Остальные — по паттерну, требуют проверки при первом реальном запуске
# (если для района приходит 0 объявлений там, где их явно быть не может —
# скорее всего, неверный слаг).
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

    def _build_url(self, district: District | None) -> str:
        slug = DISTRICT_SLUGS.get(district) if district else None
        path = f"/l/minsk-{slug}" if slug else "/l/minsk"
        return f"{BASE_HOST}{path}/snyat/komnatu"

    async def fetch(self, params: SearchParams) -> list[RawListing]:
        districts = [d for d in params.districts if d != District.ANY]
        # Без ограничений по району — один запрос по всему городу.
        targets: list[District | None] = list(districts) or [None]

        # Дедуп на случай, если один и тот же listing попал в выдачу
        # нескольких районов (маловероятно, но не бесплатно проверить).
        collected: dict[str, RawListing] = {}

        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS, timeout=self.timeout
        ) as client:
            for i, district in enumerate(targets):
                if i > 0:
                    await asyncio.sleep(self.request_delay)

                url = self._build_url(district)
                html = await self._get_with_retry(client, url)
                if html is None:
                    logger.warning("Не удалось получить %s, пропускаю", url)
                    continue

                district_label = district.value if district else None
                for listing in self._parse_html(html, district_label):
                    collected[listing.external_id] = listing

        logger.info("Kufar: собрано %s объявлений (%s запросов)", len(collected), len(targets))
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

    def _parse_html(self, html: str, district_label: str | None) -> list[RawListing]:
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
    def _make_title(cleaned: str, max_len: int = 100) -> str:
        if len(cleaned) <= max_len:
            return cleaned
        return cleaned[:max_len].rsplit(" ", 1)[0] + "…"

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
