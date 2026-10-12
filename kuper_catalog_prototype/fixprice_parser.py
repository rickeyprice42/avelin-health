"""Import Fix Price products from HTML files saved in a regular browser."""
from __future__ import annotations

import html as html_module
import json
import math
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

from slata_parser import packaging, unpack_nuxt


BASE_URL = "https://fix-price.com"
CATALOG_URL = BASE_URL + "/catalog/produkty-i-napitki"
STORE_NAME = "Fix Price"
STORE_ID = "fix-price"
PRODUCT_LINK_RE = re.compile(r"/catalog/[^\"'?#]+/p-(\d+)-[^\"'?#]+", re.IGNORECASE)
PRICE_RE = re.compile(r"(?<!\d)(\d{1,5}(?:[\s\u00a0]\d{3})*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|ля|лей)?)", re.IGNORECASE)
NUXT2_PRODUCT_RE = re.compile(r"\bproducts\s*:\s*\[", re.IGNORECASE)


def _text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html_module.unescape(str(value))).strip()


def _number(value):
    if isinstance(value, dict):
        for key in ("value", "amount", "current", "price"):
            if key in value:
                return _number(value[key])
        return ""
    if value in (None, ""):
        return ""
    match = re.search(r"\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?", str(value))
    if not match:
        return ""
    try:
        return f"{float(match.group(0).replace(' ', '').replace(chr(160), '').replace(',', '.')):g}"
    except ValueError:
        return ""


def _product_id(url, obj=None):
    match = PRODUCT_LINK_RE.search(str(url or ""))
    if match:
        return match.group(1)
    if isinstance(obj, dict):
        for key in ("sku", "productId", "product_id", "article", "vendorCode", "id"):
            value = obj.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    return ""


def _js_string(value):
    try:
        return json.loads(f'"{value}"')
    except (json.JSONDecodeError, TypeError):
        return str(value).replace(r"\u002F", "/").replace(r'\"', '"').replace(r"\\", "\\")


def _balanced_end(source, start, opening, closing):
    depth = 0
    quote = None
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index + 1
    return -1


def _top_level_objects(array_source):
    objects = []
    index = 1
    while index < len(array_source) - 1:
        if array_source[index] == "{":
            end = _balanced_end(array_source, index, "{", "}")
            if end < 0:
                break
            objects.append(array_source[index:end])
            index = end
        else:
            index += 1
    return objects


def _js_field(source, field):
    match = re.search(rf"(?:^|[,{{])\s*{re.escape(field)}\s*:\s*\"((?:\\.|[^\"\\])*)\"", source)
    return _js_string(match.group(1)) if match else ""


def _nuxt2_products(body):
    """Read product cards from Nuxt 2's JavaScript state without executing it."""
    state_start = body.find("window.__NUXT__")
    if state_start < 0:
        return []
    state = body[state_start:]
    products = []
    seen_arrays = set()
    for match in NUXT2_PRODUCT_RE.finditer(state):
        start = match.end() - 1
        end = _balanced_end(state, start, "[", "]")
        if end < 0 or (start, end) in seen_arrays:
            continue
        seen_arrays.add((start, end))
        array_source = state[start:end]
        for item_source in _top_level_objects(array_source):
            product_id = _js_field(item_source, "sku")
            title = _js_field(item_source, "title")
            url = _js_field(item_source, "url")
            price = _js_field(item_source, "price")
            if not product_id or not title or "/p-" not in url:
                continue
            if not url.startswith(("http://", "https://", "/")):
                url = f"/catalog/{url.lstrip('/')}"
            brand_match = re.search(r"\bbrand\s*:\s*\{.*?\btitle\s*:\s*\"((?:\\.|[^\"\\])*)\"", item_source, re.DOTALL)
            products.append({
                "sku": product_id,
                "title": title,
                "url": url,
                "price": price,
                "brand": _js_string(brand_match.group(1)) if brand_match else "",
            })
    return products


def _category_from_url(url):
    path = urlparse(str(url or "")).path.strip("/").split("/")
    if len(path) >= 2 and path[0] == "catalog":
        slug = path[1]
        if slug == "produkty-i-napitki":
            return "Продукты и напитки"
        return slug.replace("-", " ").strip().capitalize()
    return "Продукты и напитки"


def _offer_price(obj):
    for key in ("price", "currentPrice", "current_price", "salePrice", "sale_price"):
        value = _number(obj.get(key))
        if value:
            return value
    offers = obj.get("offers")
    if isinstance(offers, dict):
        return _offer_price(offers)
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                value = _offer_price(offer)
                if value:
                    return value
    prices = obj.get("prices")
    if isinstance(prices, dict):
        return _offer_price(prices)
    return ""


def _brand(obj):
    value = obj.get("brand")
    if isinstance(value, dict):
        value = value.get("name") or value.get("title")
    return _text(value)


def normalize_product(obj, fallback_url="", updated_utc=None):
    name = _text(obj.get("name") or obj.get("title") or obj.get("productName"))
    raw_url = obj.get("url") or obj.get("href") or obj.get("link") or obj.get("path") or fallback_url
    url = urljoin(BASE_URL, str(raw_url or ""))
    product_id = _product_id(url, obj)
    if not name or not product_id:
        return None
    row = {
        "магазин": STORE_NAME,
        "магазин_id": STORE_ID,
        "id": product_id,
        "категория": _category_from_url(url or fallback_url),
        "название": name,
        "бренд": _brand(obj),
        "фасовка": packaging({"title": name, "weight": obj.get("weight"), "unit": obj.get("unit")}),
        "цена_руб": _offer_price(obj),
        "ссылка": url,
        "доступность": "да",
        "белки": "",
        "жиры": "",
        "углеводы": "",
        "ккал": "",
        "кбжу_на": "",
        "источник_кбжу": "",
        "использовать": "да",
        "заметка": "",
        "обновлено_utc": updated_utc or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    return row


class HtmlCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = []
        self._script = None
        self._script_attrs = {}
        self.anchors = []
        self._anchor = None
        self.canonical = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self._script = []
            self._script_attrs = attrs
        elif tag == "link" and "canonical" in str(attrs.get("rel", "")).casefold():
            self.canonical = attrs.get("href") or self.canonical
        elif tag == "a" and PRODUCT_LINK_RE.search(attrs.get("href", "")):
            self._anchor = {"href": attrs.get("href", ""), "parts": [], "alt": ""}
        elif tag == "img" and self._anchor is not None:
            self._anchor["alt"] = attrs.get("alt", "") or self._anchor["alt"]

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)
        if self._anchor is not None:
            self._anchor["parts"].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append((self._script_attrs, "".join(self._script)))
            self._script = None
            self._script_attrs = {}
        elif tag == "a" and self._anchor is not None:
            self.anchors.append(self._anchor)
            self._anchor = None


def _walk_json(value, fallback_url, updated_utc, rows):
    if isinstance(value, dict):
        row = normalize_product(value, fallback_url, updated_utc)
        if row and (
            PRODUCT_LINK_RE.search(row["ссылка"])
            or str(value.get("@type") or "").casefold() == "product"
            or (_offer_price(value) and any(key in value for key in ("sku", "productId", "article", "vendorCode")))
        ):
            rows.append(row)
        for child in value.values():
            _walk_json(child, fallback_url, updated_utc, rows)
    elif isinstance(value, list):
        for child in value:
            _walk_json(child, fallback_url, updated_utc, rows)


def products_from_html_text(body, source_url=""):
    """Extract products from a saved page or from live browser HTML."""
    collector = HtmlCollector()
    collector.feed(body)
    fallback_url = collector.canonical or source_url or CATALOG_URL
    updated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    gathered = []

    for product in _nuxt2_products(body):
        row = normalize_product(product, fallback_url, updated)
        if row:
            gathered.append(row)

    for attrs, content in collector.scripts:
        script_type = str(attrs.get("type") or "").casefold()
        script_id = str(attrs.get("id") or "")
        if "json" not in script_type and script_id != "__NUXT_DATA__":
            continue
        try:
            data = json.loads(html_module.unescape(content.strip()))
            if script_id == "__NUXT_DATA__" and isinstance(data, list):
                data = unpack_nuxt(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        _walk_json(data, fallback_url, updated, gathered)

    for anchor in collector.anchors:
        name = _text(" ".join(anchor["parts"])) or _text(anchor["alt"])
        row = normalize_product({"name": name, "url": anchor["href"]}, fallback_url, updated)
        if row:
            gathered.append(row)

    # Some saved-page formats escape product links inside a serialized state.
    for match in PRODUCT_LINK_RE.finditer(body.replace("\\/", "/")):
        url = match.group(0)
        if any(row["id"] == match.group(1) for row in gathered):
            continue
        nearby = body[max(0, match.start() - 1200): min(len(body), match.end() + 1800)]
        text_nearby = _text(re.sub(r"<[^>]+>", " ", nearby))
        # A link without a trustworthy product name is not useful and may be a recommendation asset.
        title_match = re.search(r'(?:title|name)["\']?\s*[:=]\s*["\']([^"\']{4,250})', nearby, re.IGNORECASE)
        if not title_match:
            continue
        price_match = PRICE_RE.search(text_nearby)
        obj = {"name": title_match.group(1), "url": url, "price": price_match.group(1) if price_match else ""}
        row = normalize_product(obj, fallback_url, updated)
        if row:
            gathered.append(row)

    rows = {}
    for row in gathered:
        key = row["id"]
        if key not in rows:
            rows[key] = row
        else:
            for field, value in row.items():
                if value and not rows[key].get(field):
                    rows[key][field] = value
    return list(rows.values())


def products_from_html(path):
    path = Path(path)
    body = path.read_text(encoding="utf-8", errors="replace")
    return products_from_html_text(body)


def page_count_from_html(body, products_on_page=None):
    """Return the advertised last page without assuming a fixed catalogue size."""
    link_pages = [int(value) for value in re.findall(r"[?&](?:amp;)?page=(\d+)", body)]
    link_max = max(link_pages, default=1)
    count_match = re.search(r"\bproductsCount\s*:\s*\"?(\d+)\"?", body)
    if not count_match:
        return link_max, None
    product_count = int(count_match.group(1))
    per_page = products_on_page or len(_nuxt2_products(body))
    calculated = math.ceil(product_count / per_page) if per_page else 1
    return max(1, link_max, calculated), product_count


def products_from_htmls(paths):
    products = {}
    observed = 0
    loaded = []
    complete_bundles = []
    for source in paths:
        path = Path(source)
        if not path.exists():
            raise ValueError(f"HTML-файл не найден: {path}")
        sources = []
        if path.suffix.casefold() == ".json":
            try:
                bundle = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Не удалось прочитать пакет Fix Price {path}: {exc}") from exc
            if bundle.get("format") != "fixprice-pages-v1" or not isinstance(bundle.get("pages"), list):
                raise ValueError(f"Файл {path.name} не является пакетом автосбора Fix Price.")
            declared = int(bundle.get("total_pages") or 0)
            actual = {int(parse_qs(urlparse(page.get("url") or CATALOG_URL).query).get("page", ["1"])[0]) for page in bundle["pages"] if isinstance(page, dict)}
            complete_bundles.append(0 < declared <= 10000 and actual == set(range(1, declared+1)))
            for index, page in enumerate(bundle["pages"], start=1):
                if isinstance(page, dict) and isinstance(page.get("html"), str):
                    sources.append((page["html"], page.get("url") or CATALOG_URL, f"{path} — страница {index}"))
        else:
            sources.append((path.read_text(encoding="utf-8", errors="replace"), "", str(path)))
        for body, source_url, label in sources:
            rows = products_from_html_text(body, source_url)
            loaded.append({"path": label, "products": len(rows)})
            observed += len(rows)
            for row in rows:
                products[row["id"]] = row
    stats = {
        "files": len(paths),
        "pages": len(loaded),
        "observed": observed,
        "unique": len(products),
        "duplicates": observed - len(products),
        "priced": sum(1 for row in products.values() if row.get("цена_руб")),
        "missing_prices": sum(1 for row in products.values() if not row.get("цена_руб")),
        "loaded": loaded,
        "complete_capture": bool(complete_bundles) and len(complete_bundles) == len(paths) and all(complete_bundles),
    }
    return list(products.values()), stats
