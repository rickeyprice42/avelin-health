#!/usr/bin/env python3
"""Collect products visible in a Kuper store using an ordinary Playwright browser.

The script does not bypass access screens. It records product-shaped JSON from
normal page responses and extracts visible product cards as a fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


START_URL = "https://web.kuper.ru/hlebsolx5/c?sid=70307"
HEADERS = ["магазин", "магазин_id", "id", "категория", "название", "бренд", "фасовка", "цена_руб", "ссылка", "доступность", "белки", "жиры", "углеводы", "ккал", "кбжу_на", "источник_кбжу", "кбжу_статус", "кбжу_проверено_utc", "кбжу_парсер", "состав", "использовать", "заметка", "обновлено_utc"]
NAME_KEYS = ("name", "title", "product_name", "display_name", "full_name")
ID_KEYS = ("id", "product_id", "sku", "offer_id", "item_id")
PRICE_KEYS = ("price", "current_price", "discounted_price", "price_with_discount", "sale_price", "final_price")
WEIGHT_KEYS = ("weight", "volume", "size", "amount", "packaging", "unit", "quantity")
BLOCK_TEXT = ("Отключите VPN", "Проверка, что вы человек", "Verify you are human", "Access denied", "Доступ ограничен")
STORE_FILE_ALIASES = {
    "hleb&sol": "Хлеб&Соль",
    "hleb-sol": "Хлеб&Соль",
    "hleb_sol": "Хлеб&Соль",
    "pyatorochka": "Пятёрочка",
    "pyaterochka": "Пятёрочка",
}
CATEGORY_FALLBACKS = {
    "alkogol": "Алкоголь",
    "bakaleya": "Бакалея",
    "gotovaya-eda": "Готовая еда",
    "myaso-ptitsa": "Мясо, птица",
    "kolbasi-sosiski-delikatesi": "Колбасы, сосиски, деликатесы",
    "riba-ikra-dari-morya": "Рыба, икра, дары моря",
    "moloko-yajtsa-sir-rastitelnie-produkti": "Молоко, яйца, сыр, растительные продукты",
    "moloko-sir-yajtsa-rastitelnie-produkti": "Молоко, сыр, яйца, растительные продукты",
    "khleb-khlebtsi-vipechka": "Хлеб, хлебцы, выпечка",
    "khleb-vipechka": "Хлеб, выпечка",
    "ovoshchi-frukti-orekhi": "Овощи, фрукты, орехи",
    "sladosti-sneki": "Сладости, снеки",
    "chipsi-sneki-sukhofrukti": "Чипсы, снеки, сухофрукты",
    "makaroni-spetsii-masla": "Макароны, специи, масла",
    "maslo-sousi-spetsii": "Масло, соусы, специи",
    "voda-soki-napitki": "Вода, соки, напитки",
    "chaj-kofe": "Чай, кофе",
    "konservi-solenya": "Консервы, соленья",
    "zamorozhennie-produkti": "Замороженные продукты",
    "tovari-dlya-mam-i-detej": "Товары для мам и детей",
    "tovari-dlya-zhivotnih": "Товары для животных",
    "krasota-gigiena-apteka": "Красота, гигиена, аптека",
    "vse-dlya-doma": "Всё для дома",
}
PROMO_CATEGORY_MARKERS = (
    "all-products", "bez-natsenki", "skid", "akts", "promo", "bonus",
    "rekomend", "populyar", "novink", "spets-tsena", "vse-tovari",
)


def pick(obj, keys):
    for key in keys:
        v = obj.get(key)
        if isinstance(v, (str, int, float)) and str(v).strip():
            return v
    return ""


def price(value):
    if isinstance(value, dict):
        value = pick(value, ("amount", "value", "price", "current"))
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        match = re.search(r"\d[\d\s\u00a0]*([,.]\d{1,2})?", value)
        return match.group(0).replace(" ", "").replace("\u00a0", "").replace(",", ".") if match else ""
    return ""


def product_from_json(obj, category=""):
    if not isinstance(obj, dict):
        return None
    name = pick(obj, NAME_KEYS)
    pid = pick(obj, ID_KEYS)
    raw_price = next((obj[k] for k in PRICE_KEYS if k in obj and obj[k] is not None), "")
    if not name or len(str(name)) > 240 or (not pid and raw_price == ""):
        return None
    # Reject wrapper objects and navigation nodes with product-like names.
    if not (raw_price != "" or any(k in obj for k in ("image", "images", "product_image", "barcode"))):
        return None
    image_category = obj.get("category")
    if isinstance(image_category, dict):
        image_category = pick(image_category, NAME_KEYS)
    url = pick(obj, ("url", "product_url", "web_url", "href", "link"))
    if isinstance(url, str) and url.startswith("/"):
        url = "https://web.kuper.ru" + url
    brand = obj.get("brand", "")
    if isinstance(brand, dict):
        brand = pick(brand, NAME_KEYS)
    return {"id": str(pid), "категория": str(image_category or category), "название": str(name),
            "бренд": str(brand or ""), "фасовка": str(pick(obj, WEIGHT_KEYS)),
            "цена_руб": price(raw_price), "ссылка": str(url),
            "доступность": str(pick(obj, ("available", "is_available", "in_stock"))).lower(),
            "обновлено_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}


def walk_products(root):
    stack = [(root, "")]
    seen = 0
    while stack and seen < 100000:
        node, category = stack.pop()
        seen += 1
        if isinstance(node, dict):
            if any(k in node for k in ("category_name", "category_title")):
                category = str(pick(node, ("category_name", "category_title")) or category)
            item = product_from_json(node, category)
            if item:
                yield item
            stack.extend((v, category) for v in node.values() if isinstance(v, (list, dict)))
        elif isinstance(node, list):
            stack.extend((v, category) for v in node if isinstance(v, (list, dict)))


def har_json(entry):
    """Return a decoded JSON response from a HAR entry, if one is embedded."""
    content = entry.get("response", {}).get("content", {})
    text = content.get("text")
    if not isinstance(text, str):
        return None
    if content.get("encoding") == "base64":
        try:
            text = base64.b64decode(text).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def iter_har_entries(path, chunk_size=1024 * 1024):
    """Yield HAR entries without loading a potentially huge capture into memory."""
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    eof = False
    try:
        source = path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError(f"Не удалось открыть HAR {path}: {exc}") from exc
    with source:
        while True:
            if not eof:
                chunk = source.read(chunk_size)
                if chunk:
                    buffer += chunk
                else:
                    eof = True
            if not started:
                marker = re.search(r'"entries"\s*:\s*\[', buffer)
                if marker:
                    buffer = buffer[marker.end():]
                    started = True
                elif eof:
                    raise ValueError(f"В HAR {path} не найден массив log.entries")
                else:
                    # The marker is near the beginning, but retain a short suffix
                    # in case it falls on a chunk boundary.
                    buffer = buffer[-128:]
                    continue
            while started:
                buffer = buffer.lstrip()
                if buffer.startswith(","):
                    buffer = buffer[1:]
                    continue
                if buffer.startswith("]"):
                    return
                if not buffer:
                    break
                try:
                    entry, end = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    if eof:
                        raise ValueError(f"Повреждённый или неполный HAR: {path}")
                    break
                if isinstance(entry, dict):
                    yield entry
                buffer = buffer[end:]
            if eof:
                raise ValueError(f"Повреждённый или неполный HAR: {path}")


def add_category_names(root, names):
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            slug = node.get("slug")
            name = node.get("name")
            if isinstance(slug, str) and isinstance(name, str) and slug and name:
                normalized = slug.strip("/")
                names[normalized] = name
                names[normalized.split("/")[-1]] = name
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend(v for v in node if isinstance(v, (dict, list)))


def store_name_from_json(root):
    if not isinstance(root, dict):
        return ""
    data = root.get("data", root)
    if not isinstance(data, dict):
        return ""
    retailer = data.get("retailer")
    if isinstance(retailer, dict) and isinstance(retailer.get("name"), str):
        return retailer["name"].strip()
    return ""


def category_from_permalink(permalink, category_names):
    normalized = str(permalink or "").strip("/")
    if normalized in category_names:
        return category_names[normalized]
    slug = normalized.split("/")[-1]
    if slug in category_names:
        return category_names[slug]
    clean_slug = re.sub(r"-[0-9a-f]{6,}$", "", slug).removesuffix("-copy")
    for key, name in CATEGORY_FALLBACKS.items():
        if clean_slug == key or clean_slug.startswith(key + "-"):
            return name
    # Keep an understandable fallback when the HAR does not contain the category tree.
    return clean_slug.replace("-", " ").strip()


def category_priority(permalink, category_names):
    normalized = str(permalink or "").strip("/")
    slug = normalized.split("/")[-1]
    clean_slug = re.sub(r"-[0-9a-f]{6,}$", "", slug).removesuffix("-copy")
    if normalized in category_names or slug in category_names:
        return 100 + normalized.count("/")
    if any(clean_slug == key or clean_slug.startswith(key + "-") for key in CATEGORY_FALLBACKS):
        return 80 + normalized.count("/")
    if any(marker in clean_slug for marker in PROMO_CATEGORY_MARKERS):
        return 0
    return 20 + normalized.count("/")


def product_from_entities(obj, category, store_id="", store_name=""):
    if not isinstance(obj, dict):
        return None
    pid = pick(obj, ("id", "product_id", "productID", "sku", "retailer_sku"))
    name = pick(obj, NAME_KEYS)
    if not pid or not name:
        return None
    url = pick(obj, ("canonical_url", "permalink", "url"))
    if isinstance(url, str) and url.startswith("/"):
        url = "https://web.kuper.ru" + url
    brand = obj.get("brand", "")
    if isinstance(brand, dict):
        brand = pick(brand, NAME_KEYS)
    return {
        "магазин": str(store_name or ""),
        "магазин_id": str(store_id or ""),
        "id": str(pid),
        "категория": category,
        "название": str(name),
        "бренд": str(brand or ""),
        "фасовка": str(pick(obj, ("human_volume", "humanVolume", "weight", "volume"))),
        "цена_руб": price(pick(obj, ("price", "unit_price", "unitPrice"))),
        "ссылка": str(url or ""),
        "доступность": str(obj.get("available", "")).lower(),
        "обновлено_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    }


def products_from_hars(paths):
    """Extract and deduplicate catalogue products embedded in Kuper HAR files."""
    loaded = []
    for path in paths:
        candidates = sorted(path.glob("*.har")) if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file():
                raise ValueError(f"HAR-файл не найден: {candidate}")
            loaded.append(candidate)
    if not loaded:
        raise ValueError("HAR-файлы не найдены")

    category_names = {}
    store_names = {}
    for candidate in loaded:
        for entry in iter_har_entries(candidate):
            path = urlsplit(entry.get("request", {}).get("url", "")).path
            category_match = re.fullmatch(r"/api/v3/stores/(\d+)/categories", path)
            store_match = re.fullmatch(r"/api/v3/mweb/stores/(\d+)", path)
            if category_match:
                add_category_names(har_json(entry), category_names)
            elif store_match:
                name = store_name_from_json(har_json(entry))
                if name:
                    store_names[store_match.group(1)] = name

    products = {}
    coverage = {}
    entity_responses = 0
    observed = 0
    store_counts = {}
    for candidate in loaded:
        for entry in iter_har_entries(candidate):
            request = entry.get("request", {})
            response = entry.get("response", {})
            if urlsplit(request.get("url", "")).path != "/api/v3/entities" or response.get("status") != 200:
                continue
            body = har_json(entry)
            if not isinstance(body, dict):
                continue
            try:
                post = json.loads(request.get("postData", {}).get("text", "{}"))
            except json.JSONDecodeError:
                post = {}
            permalink = post.get("category_permalink", "") if isinstance(post, dict) else ""
            store_id = str(post.get("store_id", "")) if isinstance(post, dict) else ""
            fallback_store = STORE_FILE_ALIASES.get(candidate.stem.casefold(), candidate.stem)
            store_name = store_names.get(store_id, fallback_store)
            category = category_from_permalink(permalink, category_names)
            priority = category_priority(permalink, category_names)
            meta = body.get("meta", {})
            if isinstance(meta, dict) and permalink:
                try:
                    current_page = int(meta.get("current_page"))
                    total_pages = int(meta.get("total_pages"))
                except (TypeError, ValueError):
                    current_page = total_pages = 0
                if current_page > 0 and total_pages > 0:
                    coverage_key = f"{store_id}|{permalink}"
                    item_coverage = coverage.setdefault(coverage_key, {"store": store_name, "category": category, "pages": set(), "total_pages": 0})
                    item_coverage["pages"].add(current_page)
                    item_coverage["total_pages"] = max(item_coverage["total_pages"], total_pages)
            entity_responses += 1
            for entity in body.get("entities", []):
                raw = entity.get("product") if isinstance(entity, dict) else None
                item = product_from_entities(raw, category, store_id, store_name)
                if not item:
                    continue
                observed += 1
                key = f"{store_id}|{item['id']}"
                previous = products.get(key)
                if previous is None or priority >= previous[0]:
                    products[key] = (priority, merge(previous[1], item) if previous else item)
                else:
                    products[key] = (previous[0], merge(previous[1], {k: v for k, v in item.items() if k != "категория"}))
    incomplete_categories = []
    for coverage_key, item_coverage in coverage.items():
        expected = set(range(1, item_coverage["total_pages"] + 1))
        missing = sorted(expected - item_coverage["pages"])
        if missing:
            incomplete_categories.append({
                "category": item_coverage["category"],
                "store": item_coverage["store"],
                "permalink": coverage_key.split("|", 1)[-1],
                "missing_pages": missing,
                "total_pages": item_coverage["total_pages"],
            })
    for _, item in products.values():
        store = item.get("магазин") or "Неизвестный магазин"
        store_counts[store] = store_counts.get(store, 0) + 1
    stats = {
        "files": len(loaded),
        "entity_responses": entity_responses,
        "observed": observed,
        "unique": len(products),
        "known_category_names": len(category_names),
        "incomplete_categories": incomplete_categories,
        "stores": store_counts,
        "complete_capture": bool(loaded) and not incomplete_categories and all(
            candidate.name.casefold().endswith(".complete.har") for candidate in loaded
        ),
    }
    return [value[1] for value in products.values()], stats


def merge(old, new):
    for key, value in new.items():
        if value != "":
            old[key] = value
    return old


def read_existing(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def save(path, existing, gathered):
    # Store-scoped IDs prevent collisions between different retailers.
    def identity(item):
        store = item.get("магазин_id") or item.get("магазин", "").casefold()
        product = item.get("id") or item.get("ссылка") or (item.get("название", "").casefold() + "|" + item.get("фасовка", "").casefold())
        return f"{store}|{product}" if product else ""
    rows = {identity(x): dict(x) for x in existing if identity(x)}
    for item in gathered:
        key = identity(item)
        if key:
            # Migrate rows created before store columns were introduced.
            legacy_key = f"|{item.get('id', '')}"
            if key not in rows and legacy_key in rows:
                rows[key] = rows.pop(legacy_key)
            rows[key] = merge(rows.get(key, {}), item)
    path.parent.mkdir(parents=True, exist_ok=True)
    extra_headers = list(dict.fromkeys(k for row in existing for k in row if k not in HEADERS))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS + extra_headers, delimiter=";")
        writer.writeheader()
        writer.writerows(rows.values())
    return len(rows)


async def main():
    parser = argparse.ArgumentParser(description="Собрать каталог конкретного магазина Купера в редактируемый CSV")
    parser.add_argument("--url", default=START_URL)
    parser.add_argument("--output", type=Path, default=Path("hlebsol_catalog.csv"))
    parser.add_argument("--har", type=Path, nargs="+", help="Импортировать товары из одного или нескольких HAR-файлов без запуска браузера")
    parser.add_argument("--profile", type=Path, default=Path(".kuper_edge_profile"))
    parser.add_argument(
        "--browser",
        choices=("edge", "chromium"),
        default="edge",
        help="Браузер для запуска: обычный Microsoft Edge (по умолчанию) или Chromium Playwright",
    )
    parser.add_argument("--manual", action="store_true", help="Самостоятельно переходить по категориям; Enter завершает сбор")
    parser.add_argument("--max-pages", type=int, default=80)
    parser.add_argument("--scrolls", type=int, default=12)
    args = parser.parse_args()
    if args.max_pages < 1 or args.scrolls < 0:
        parser.error("--max-pages должен быть >= 1, --scrolls >= 0")

    if args.har:
        try:
            products, stats = products_from_hars(args.har)
        except ValueError as exc:
            parser.error(str(exc))
        if not products:
            print("В HAR не найдены товарные ответы /api/v3/entities. Пустой каталог не создаётся.")
            return 1
        count = save(args.output, read_existing(args.output), products)
        print(
            f"HAR-файлов: {stats['files']}, ответов каталога: {stats['entity_responses']}, "
            f"товарных записей: {stats['observed']}, уникальных товаров в импорте: {stats['unique']}"
        )
        for store, store_count in sorted(stats["stores"].items()):
            print(f"  {store}: {store_count} товаров")
        if not stats["known_category_names"]:
            print("Названия категорий не найдены в HAR; сохранены читаемые части адресов категорий.")
        for incomplete in stats["incomplete_categories"]:
            missing = ", ".join(str(x) for x in incomplete["missing_pages"])
            print(
                f"ВНИМАНИЕ: {incomplete['store']}, категория «{incomplete['category']}» записана не полностью: "
                f"нет страниц {missing} из {incomplete['total_pages']}."
            )
        print(f"Готово: {count} строк → {args.output.resolve()}")
        return 0

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("Установите Playwright: py -m pip install playwright; py -m playwright install chromium") from exc
    products = []
    requests = {}
    tasks = set()

    async with async_playwright() as p:
        launch_options = {
            "user_data_dir": str(args.profile.resolve()),
            "headless": False,
            "viewport": {"width": 1400, "height": 950},
        }
        if args.browser == "edge":
            launch_options["channel"] = "msedge"
        context = await p.chromium.launch_persistent_context(**launch_options)
        page = context.pages[0] if context.pages else await context.new_page()

        async def record(response):
            url = response.url
            path = urlsplit(url)
            if not path.hostname or not path.hostname.endswith("kuper.ru"):
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type or response.status != 200:
                return
            # Ignore tracking and avoid retaining query strings, cookies or raw responses.
            try:
                body = await response.json()
            except Exception:
                return
            found = list(walk_products(body))
            if found:
                products.extend(found)
                safe_url = urlunsplit((path.scheme, path.netloc, path.path, "", ""))
                requests[safe_url] = requests.get(safe_url, 0) + len(found)
                print(f"JSON: +{len(found)} товаров ({path.path})")

        def on_response(response):
            task = asyncio.create_task(record(response))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        context.on("response", on_response)
        await page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        page_text = await page.locator("body").inner_text()
        if any(marker.casefold() in page_text.casefold() for marker in BLOCK_TEXT):
            print("Доступ к каталогу ограничен на этой сети/в этом браузере. Скрипт не обходит проверку.")
            await context.close()
            return 2

        print("Браузер открыт. Если магазин просит город или адрес, выберите их в окне браузера.")
        if args.manual:
            await asyncio.to_thread(input, "Откройте нужные категории, затем нажмите Enter здесь... ")
        else:
            visited = set()
            queue = [page.url]
            while queue and len(visited) < args.max_pages:
                url = queue.pop(0)
                if url in visited:
                    continue
                if url != page.url:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as exc:
                        print(f"Пропущена страница: {type(exc).__name__}: {url}")
                        continue
                visited.add(url)
                for _ in range(args.scrolls):
                    await page.mouse.wheel(0, 1400)
                    await page.wait_for_timeout(650)
                # Page links are read from the current UI, not guessed API endpoints.
                links = await page.locator("a[href]").evaluate_all("els => els.map(e => ({url:e.href,text:(e.innerText||'').trim()}))")
                current = urlsplit(args.url)
                store_prefix = current.path.split("/c")[0]
                for link in links:
                    candidate = urlsplit(link["url"])
                    is_catalogue = candidate.path.startswith(store_prefix + "/c")
                    if candidate.hostname == current.hostname and is_catalogue and link["url"] not in visited and link["url"] not in queue:
                        queue.append(link["url"])
                # Visible card fallback: price-bearing links only.
                cards = await page.locator("a[href]").evaluate_all("""els => els.map(e => ({url:e.href, text:(e.innerText||'').trim()})).filter(x => x.text.length < 300 && /\\d[\\d\\s]*[₽р]/i.test(x.text))""")
                for card in cards:
                    lines = [x.strip() for x in card["text"].split("\n") if x.strip()]
                    title = next((x for x in lines if len(x) > 5 and not re.search(r"\d[\d\s]*[₽р]", x)), "")
                    cost = next((price(x) for x in lines if re.search(r"\d[\d\s]*[₽р]", x)), "")
                    if title and cost:
                        products.append({"id": "", "категория": "", "название": title, "цена_руб": cost, "ссылка": card["url"], "обновлено_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")})
                print(f"Страниц: {len(visited)}, в очереди: {len(queue)}, найдено записей: {len(products)}")
                if any(marker.casefold() in (await page.locator("body").inner_text()).casefold() for marker in BLOCK_TEXT):
                    print("Сайт показал ограничение доступа; сбор остановлен.")
                    break
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if products:
            count = save(args.output, read_existing(args.output), products)
            print(f"Готово: {count} строк → {args.output.resolve()}")
        else:
            print("Товары не найдены. Пустой каталог не создаётся.")
        report = args.output.with_suffix(".requests.json")
        report.write_text(json.dumps({"source": args.url, "collected_at": datetime.now(timezone.utc).isoformat(), "json_product_routes": requests, "items_observed": len(products)}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Маршруты JSON с товарами → {report.resolve()}")
        await context.close()
    return 0 if products else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
