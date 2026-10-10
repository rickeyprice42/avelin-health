"""Automatic catalogue collector for shop.slata.com.

Slata renders its catalogue with Nuxt and embeds the page data in a
``#__NUXT_DATA__`` JSON script.  The collector opens Edge once, then downloads
the remaining server-rendered catalogue pages through the browser context.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
from datetime import datetime, timezone
from typing import Callable


BASE_URL = "https://shop.slata.com"
CATALOG_URL = f"{BASE_URL}/catalog"
STORE_NAME = "Слата"
STORE_ID = "slata-online"

# Food sections useful for recipe and price analysis.  Child products are
# already included by the corresponding top-level page.
FOOD_CATEGORIES = {
    "ovoschi-frukty-griby-zelen": "Овощи, фрукты, грибы, зелень",
    "moloko-syr-yaytsa": "Молоко, сыр, яйца",
    "myaso-ptitsa-delikatesy": "Мясо, птица, деликатесы",
    "hleb-i-vypechka": "Хлеб и выпечка",
    "bakaleya": "Бакалея",
    "soki-vody-napitki": "Соки, воды, напитки",
    "sladosti-i-sneki": "Сладости и снеки",
    "gotovaya-eda": "Готовая еда",
    "ryba-i-moreprodukty": "Рыба и морепродукты",
    "zamorozhennye-produkty": "Замороженные продукты",
    "kofe-chay-kakao": "Кофе, чай, какао",
}

NUXT_RE = re.compile(r'<script[^>]*id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
PACKAGE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(кг|килограмм(?:а|ов)?|г|гр|грамм(?:а|ов)?|л|литр(?:а|ов)?|мл|шт|штук(?:а|и)?)\b",
    re.IGNORECASE,
)


def unpack_nuxt(values):
    """Decode Nuxt's devalue-style flattened JSON array."""
    cache = {}

    def dereference(index):
        if isinstance(index, bool) or index is None:
            return index
        if not isinstance(index, int):
            return index
        if index < 0:
            return None
        if index >= len(values):
            return index
        if index in cache:
            return cache[index]
        cache[index] = None
        cache[index] = hydrate(values[index])
        return cache[index]

    def hydrate(value):
        if isinstance(value, list):
            if value and value[0] in {"ShallowReactive", "Reactive", "Ref", "ShallowRef", "EmptyRef"}:
                return dereference(value[1]) if len(value) > 1 else None
            return [dereference(item) for item in value]
        if isinstance(value, dict):
            return {key: dereference(item) for key, item in value.items()}
        return value

    return dereference(0)


def find_catalog(value):
    """Find the catalogue payload without depending on Nuxt's generated key."""
    if isinstance(value, dict):
        if isinstance(value.get("products"), list) and "pageCount" in value and "count" in value:
            return value
        for child in value.values():
            found = find_catalog(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_catalog(child)
            if found is not None:
                return found
    return None


def catalog_from_html(body):
    match = NUXT_RE.search(body)
    if not match:
        raise ValueError("На странице «Слаты» не найден блок __NUXT_DATA__.")
    values = json.loads(html.unescape(match.group(1)))
    catalog = find_catalog(unpack_nuxt(values))
    if catalog is None:
        raise ValueError("Во встроенных данных «Слаты» не найден каталог товаров.")
    return catalog


def _plain_number(value):
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def packaging(product):
    title = str(product.get("title") or "")
    matches = list(PACKAGE_RE.finditer(title))
    if matches:
        amount, unit = matches[-1].groups()
        aliases = {"гр": "г", "штука": "шт", "штуки": "шт"}
        return f"{amount.replace('.', ',')} {aliases.get(unit.casefold(), unit.casefold())}"
    weight = product.get("weight")
    if isinstance(weight, (int, float)) and weight > 0:
        if weight < 1:
            return f"{weight * 1000:g} г"
        return f"{weight:g} кг"
    return str(product.get("unit") or "")


def _nutrition(product):
    result = {
        "белки": "", "жиры": "", "углеводы": "", "ккал": "",
        "кбжу_на": "", "источник_кбжу": "",
    }
    nutrients = product.get("nutrients")
    if not isinstance(nutrients, dict):
        return result
    aliases = {
        "protein": "белки", "proteins": "белки", "белки": "белки",
        "fat": "жиры", "fats": "жиры", "жиры": "жиры",
        "carbohydrate": "углеводы", "carbohydrates": "углеводы", "углеводы": "углеводы",
        "calories": "ккал", "calorie": "ккал", "kcal": "ккал", "ккал": "ккал",
    }
    for key, value in nutrients.items():
        target = aliases.get(str(key).casefold())
        if target:
            result[target] = _plain_number(value)
    if any(result[key] for key in ("белки", "жиры", "углеводы", "ккал")):
        result["источник_кбжу"] = "данные магазина Слата"
        # The shop payload does not always label the basis explicitly, so we
        # leave it blank instead of silently assuming “per 100 g”.
    return result


def normalize_product(product, category_slug, category_name, updated_utc=None):
    product_id = str(product.get("vendorCode") or "").strip()
    title = str(product.get("title") or "").strip().removeprefix("- ").strip()
    row = {
        "магазин": STORE_NAME,
        "магазин_id": STORE_ID,
        "id": product_id,
        "категория": category_name,
        "название": title,
        "бренд": str(product.get("brand") or "").strip(),
        "фасовка": packaging(product),
        "цена_руб": _plain_number(product.get("price")),
        "ссылка": f"{CATALOG_URL}/{category_slug}",
        "доступность": "да",
        "использовать": "да",
        "заметка": "",
        "обновлено_utc": updated_utc or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    row.update(_nutrition(product))
    return row


async def collect_slata_products(
    progress: Callable[[str], None] | None = None,
    max_pages_per_category: int | None = None,
    concurrency: int = 3,
):
    """Collect food products and return ``(items, stats)``.

    ``max_pages_per_category`` is intended for diagnostics.  The GUI leaves it
    unset and therefore collects every page advertised by the site.
    """
    if max_pages_per_category is not None and max_pages_per_category < 1:
        raise ValueError("max_pages_per_category должен быть не меньше 1")
    if concurrency < 1:
        raise ValueError("concurrency должен быть не меньше 1")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("Для «Слаты» нужен Playwright: py -m pip install playwright") from exc

    def report(message):
        if progress:
            progress(message)

    report("Открываю «Слату» в Edge…")
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(locale="ru-RU")
            page = await context.new_page()
            await page.goto(CATALOG_URL, wait_until="domcontentloaded", timeout=90000)
            await page.locator("#__NUXT_DATA__").wait_for(state="attached", timeout=30000)

            semaphore = asyncio.Semaphore(concurrency)

            async def fetch(category_slug, page_number, attempts=4):
                url = f"{CATALOG_URL}/{category_slug}"
                if page_number > 1:
                    url += f"?page={page_number}"
                last_error = None
                for attempt in range(attempts):
                    try:
                        async with semaphore:
                            response = await context.request.get(
                                url,
                                timeout=90000,
                                headers={"Cache-Control": "no-cache"},
                            )
                        if not response.ok:
                            raise RuntimeError(f"HTTP {response.status}")
                        return catalog_from_html(await response.text())
                    except Exception as exc:
                        last_error = exc
                        if attempt < attempts - 1:
                            await asyncio.sleep(min(12, 1.5 * (attempt + 1)))
                raise RuntimeError(f"Не удалось загрузить {url}: {last_error}")

            report("Определяю объём каталога «Слаты»…")
            first_results = await asyncio.gather(*(fetch(slug, 1) for slug in FOOD_CATEGORIES))
            page_limits = {}
            for slug, data in zip(FOOD_CATEGORIES, first_results):
                advertised = max(1, int(data.get("pageCount") or 1))
                page_limits[slug] = min(advertised, max_pages_per_category) if max_pages_per_category else advertised

            total_pages = sum(page_limits.values())
            completed_pages = len(first_results)
            rows_by_id = {}
            row_ranks = {}
            category_ranks = {slug: rank for rank, slug in enumerate(FOOD_CATEGORIES)}
            observed = 0
            updated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

            def absorb(slug, data):
                nonlocal observed
                category_name = FOOD_CATEGORIES[slug]
                for product in data.get("products") or []:
                    if not isinstance(product, dict) or not product.get("vendorCode"):
                        continue
                    observed += 1
                    row = normalize_product(product, slug, category_name, updated)
                    rank = category_ranks[slug]
                    if row["id"] not in rows_by_id or rank < row_ranks[row["id"]]:
                        rows_by_id[row["id"]] = row
                        row_ranks[row["id"]] = rank

            for slug, data in zip(FOOD_CATEGORIES, first_results):
                absorb(slug, data)
            report(f"«Слата»: загружено {completed_pages} из {total_pages} страниц…")

            async def fetch_and_absorb(slug, page_number):
                nonlocal completed_pages
                try:
                    data = await fetch(slug, page_number)
                except Exception as exc:
                    return slug, page_number, exc
                absorb(slug, data)
                completed_pages += 1
                if completed_pages == total_pages or completed_pages % 5 == 0:
                    report(f"«Слата»: загружено {completed_pages} из {total_pages} страниц…")
                return None

            results = await asyncio.gather(*(
                fetch_and_absorb(slug, page_number)
                for slug, limit in page_limits.items()
                for page_number in range(2, limit + 1)
            ))
            failures = [result for result in results if result is not None]
            if failures:
                report(f"«Слата»: повторяю отдельно {len(failures)} временно недоступных страниц…")
            unresolved = []
            for slug, page_number, original_error in failures:
                try:
                    data = await fetch(slug, page_number, attempts=6)
                    absorb(slug, data)
                    completed_pages += 1
                    report(f"«Слата»: загружено {completed_pages} из {total_pages} страниц…")
                except Exception as exc:
                    unresolved.append((slug, page_number, exc or original_error))
            if unresolved:
                details = ", ".join(f"{slug}, стр. {number}" for slug, number, _ in unresolved)
                raise RuntimeError(f"Не удалось получить страницы после повторных попыток: {details}")
        finally:
            await browser.close()

    stats = {
        "store": STORE_NAME,
        "categories": len(FOOD_CATEGORIES),
        "pages": completed_pages,
        "expected_pages": total_pages,
        "observed": observed,
        "unique": len(rows_by_id),
        "duplicates": observed - len(rows_by_id),
        "limited": max_pages_per_category is not None,
    }
    return list(rows_by_id.values()), stats
