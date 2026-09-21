"""Диагностика: почему в карусель карточки подмешиваются фото ДРУГИХ
объявлений. Гипотеза — fetch_photos() сканирует ВСЮ страницу объявления
без разбора на "своя галерея" vs "похожие объявления снизу". Скрипт сам
берёт свежее объявление (через обычный fetch()) и показывает подробную
структуру img-тегов на его странице. Ничего не меняет, только печатает.
Запуск: python3 debug_gallery.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

from database.models import District
from sources.base import SearchParams
from sources.kufar import KufarSource, DEFAULT_HEADERS, STATIC_ASSET_DOMAIN


def class_chain(tag, depth=6) -> str:
    """Цепочка классов от самого img вверх по родителям — чтобы понять,
    в каком контейнере он лежит (своя галерея / блок похожих / что-то ещё)."""
    parts = []
    node = tag
    for _ in range(depth):
        if node is None or node.name is None:
            break
        classes = " ".join(node.get("class", []))
        parts.append(f"<{node.name} class='{classes}'>" if classes else f"<{node.name}>")
        node = node.parent
    return " < ".join(parts)


async def main() -> None:
    source = KufarSource()
    listings = await source.fetch(SearchParams(districts=[District.CENTRALNY], categories=["room"]))
    if not listings:
        print("Не нашлось ни одного объявления — сначала разберёмся с этим.")
        return

    listing = listings[0]
    print(f"Объявление: {listing.external_id}")
    print(f"Страница: {listing.url}")
    print(f"Превью с карточки поиска (image_url): {listing.image_url}")
    print("=" * 70)

    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(listing.url)
        print(f"HTTP статус страницы объявления: {resp.status_code}")
        if resp.status_code != 200:
            return
        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    all_imgs = soup.find_all("img")
    print(f"\nВсего <img> на странице объявления: {len(all_imgs)}")

    candidates = []
    for img in all_imgs:
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        if STATIC_ASSET_DOMAIN in src:
            continue
        if src.lower().endswith(".svg"):
            continue
        candidates.append((src, img))

    print(f"Из них проходят текущий фильтр (не иконки/не svg): {len(candidates)}\n")

    for i, (src, img) in enumerate(candidates[:25]):
        print(f"[{i}] {src}")
        print(f"    Цепочка контейнеров: {class_chain(img)}")
        print("-" * 70)

    print("\nПоиск контейнеров с 'подозрительными' классами (similar/related/recommend/slider/gallery/carousel):")
    keywords = ["similar", "related", "recommend", "slider", "gallery", "carousel", "swiper"]
    seen = set()
    for tag in soup.find_all(class_=True):
        classes = " ".join(tag.get("class", []))
        low = classes.lower()
        if any(k in low for k in keywords) and classes not in seen:
            seen.add(classes)
            img_count = len(tag.find_all("img"))
            print(f" - <{tag.name} class='{classes}'>  (img внутри: {img_count})")


if __name__ == "__main__":
    asyncio.run(main())
