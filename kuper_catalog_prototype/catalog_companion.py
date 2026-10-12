"""Authenticated loopback bridge for the ordinary-browser overnight extension."""
from __future__ import annotations
import argparse
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from catalog_export import build_catalog_files
from kuper_parser import products_from_hars
from fixprice_parser import products_from_htmls
from nutrition_enrichment import prepare_nutrition_queues, import_nutrition_results
from slata_parser import FOOD_CATEGORIES, catalog_from_html, normalize_product
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_product_catalog import import_catalog


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class Companion:
    def __init__(self, output, db=None):
        self.output = Path(output)
        self.inbox = self.output / "Ночной сбор"
        self.db = Path(db) if db else None
        self.lock = threading.Lock()

    def sync(self):
        if self.db:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            return import_catalog(self.output / "Все магазины.csv", self.db, replace_stores=True)
        return None

    def capture(self, payload):
        kind, data = payload.get("kind"), payload.get("data")
        if kind == "kuper":
            if not isinstance(data, dict) or not isinstance(data.get("log", {}).get("entries"), list):
                raise ValueError("Некорректный HAR")
            # Never persist browser headers/cookies even if a caller supplies them.
            for entry in data["log"]["entries"]:
                for section in ("request", "response"):
                    entry.get(section, {}).update(headers=[], cookies=[])
                post = entry.get("request", {}).get("postData")
                if post:
                    values = json.loads(post.get("text", "{}"))
                    post["text"] = json.dumps({key: values[key] for key in ("store_id", "category_permalink", "page", "per_page") if key in values})
            path = self.inbox / "kuper.complete.har"
            atomic_json(path, data)
            items, stats = products_from_hars([path])
            complete = stats.get("complete_capture", False)
        elif kind == "fixprice":
            if not isinstance(data, dict) or data.get("format") != "fixprice-pages-v1":
                raise ValueError("Некорректный пакет Fix Price")
            path = self.inbox / "fixprice.json"
            atomic_json(path, data)
            items, stats = products_from_htmls([path])
            complete = stats.get("complete_capture", False)
        elif kind == "slata":
            if not isinstance(data, dict) or data.get("format") != "slata-pages-v1": raise ValueError("Некорректный пакет Слаты")
            path = self.inbox / "slata.json"
            atomic_json(path, data)
            items_by_id, coverage, limits = {}, {}, {}
            stamp = datetime.now(timezone.utc).isoformat()
            for page in data.get("pages", []):
                category = page["category"]
                if category not in FOOD_CATEGORIES: raise ValueError("Неизвестная категория Слаты")
                catalog = catalog_from_html(page["html"])
                coverage.setdefault(category, set()).add(int(page["page"]))
                limits[category] = max(limits.get(category, 1), int(catalog.get("pageCount") or 1))
                for product in catalog.get("products", []):
                    if isinstance(product, dict) and product.get("vendorCode"):
                        item = normalize_product(product, category, FOOD_CATEGORIES[category], stamp)
                        items_by_id.setdefault(item["id"], item)
            items = list(items_by_id.values())
            complete = all(category in coverage and coverage[category] == set(range(1, limits[category]+1)) for category in FOOD_CATEGORIES)
        else:
            raise ValueError("Неизвестный сборщик")
        if not items:
            raise ValueError("Товары не найдены; прежний каталог сохранён")
        files = build_catalog_files(items, self.output, replace_stores=complete)
        return {"products": len(items), "complete": complete, "rows": files["combined"]["rows"], "avelin": self.sync()}

    def queues(self, refresh=False):
        stats = prepare_nutrition_queues(self.output, refresh=refresh, max_age_days=30)
        return {site: json.loads(path.read_text(encoding="utf-8")) for site, path in stats["queue_paths"].items()}

    def nutrition(self, payload):
        if payload.get("site") not in {"kuper", "fixprice"} or payload.get("format") != "nutrition-batch-v1":
            raise ValueError("Некорректный пакет КБЖУ")
        path = self.inbox / f"nutrition-{payload['site']}.json"
        atomic_json(path, payload)
        if not payload.get("results"):
            return {"saved": True, "rows_updated": 0}
        stats = import_nutrition_results([path], self.output)
        return {"saved": True, "rows_updated": stats["rows_updated"], "rejected": stats["rejected"], "avelin": self.sync()}


def make_handler(companion, token):
    class Handler(BaseHTTPRequestHandler):
        def response(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            origin = self.headers.get("Origin", "")
            if origin.startswith("chrome-extension://"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            host = self.headers.get("Host", "").split(":")[0]
            supplied = self.headers.get("X-Avelin-Token", "")
            return host in {"127.0.0.1", "localhost"} and secrets.compare_digest(supplied, token)

        def do_OPTIONS(self):
            origin = self.headers.get("Origin", "")
            if not origin.startswith("chrome-extension://"):
                return self.response({"error": "Forbidden origin"}, 403)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Avelin-Token")
            self.end_headers()

        def do_GET(self):
            if not self.authorized(): return self.response({"error": "Нужен ключ локального помощника"}, 401)
            try:
                with companion.lock:
                    if self.path == "/status": return self.response({"ok": True, "output": str(companion.output)})
                    if urlparse(self.path).path == "/queues": return self.response(companion.queues(refresh=urlparse(self.path).query == "refresh=1"))
                self.response({"error": "Not found"}, 404)
            except Exception as error: self.response({"error": str(error)}, 400)

        def do_POST(self):
            if not self.authorized(): return self.response({"error": "Нужен ключ локального помощника"}, 401)
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 100_000_000: raise ValueError("Некорректный размер пакета")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict): raise ValueError("Нужен JSON-объект")
                with companion.lock:
                    if self.path == "/capture": return self.response(companion.capture(payload))
                    if self.path == "/nutrition": return self.response(companion.nutrition(payload))
                self.response({"error": "Not found"}, 404)
            except Exception as error: self.response({"error": str(error)}, 400)

        def log_message(self, *_): pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "Каталоги магазинов")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "avelin-health.db")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    config_path = ROOT / ".local" / "catalog-collector.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {"token": secrets.token_urlsafe(32)}
    config.update(output=str(args.output.resolve()), port=args.port)
    atomic_json(config_path, config)
    print(f"Локальный помощник: http://127.0.0.1:{args.port}")
    print(f"Ключ для расширения находится в {config_path}")
    print(f"Результаты: {args.output.resolve()}")
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Companion(args.output, args.db), config["token"])).serve_forever()


if __name__ == "__main__": main()
