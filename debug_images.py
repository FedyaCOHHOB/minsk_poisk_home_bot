"""Разовый диагностический скрипт — печатает сырую разметку первых
карточек объявлений, чтобы понять, куда делись картинки. Не трогает
основной код, ничего не меняет. Запуск: python3 debug_images.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

from sources.kufar import DEFAULT_HEADERS, LISTING_HREF_RE, BASE_HOST


async def main() -> None:
    url = f"{BASE_HOST}/l/minsk/snyat/komnatu"
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10.0) as client:
        resp = await client.get(url)
        print(f"HTTP статус: {resp.status_code}\n")
        if resp.status_code != 200:
            print("Не 200 — дальше смысла нет, пришли этот статус мне.")
            return
        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    print(f"Всего <img> на странице: {len(soup.find_all('img'))}")
    print(f"Всего <picture> на странице: {len(soup.find_all('picture'))}\n")

    shown = 0
    for a in soup.find_all("a", href=True):
        if not LISTING_HREF_RE.search(a["href"]):
            continue
        shown += 1
        print("=" * 70)
        print(f"КАРТОЧКА #{shown} — ссылка: {a['href']}")
        print("-" * 70)
        print("Сырой HTML самой <a> (первые 3000 символов):")
        print(str(a)[:3000])

        parent = a.parent
        if parent is not None:
            print("-" * 70)
            imgs_in_parent = parent.find_all("img")
            pics_in_parent = parent.find_all("picture")
            print(f"В родительском элементе <a>: <img> — {len(imgs_in_parent)}, <picture> — {len(pics_in_parent)}")
            if imgs_in_parent:
                print("Первый найденный <img> у родителя:")
                print(str(imgs_in_parent[0])[:1000])

        if shown >= 3:
            break

    if shown == 0:
        print("Ни одной карточки не распозналось регуляркой LISTING_HREF_RE — это отдельная, более серьёзная проблема (верстка ссылок изменилась сильнее, чем просто картинки).")


if __name__ == "__main__":
    asyncio.run(main())
