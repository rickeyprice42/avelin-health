"""Catalog-backed recipe cards and persistent shopping lists."""
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

INSTRUCTIONS = """
Когда предлагаешь полный рецепт, сначала найди реальные товары через search_store_products.
Затем вызови build_recipe_card с точными name/store_name из каталога, количеством для
рецепта amount, числом покупаемых упаковок packs, шагами и КБЖУ НА ОДНУ ПОРЦИЮ.
КБЖУ оцени диапазоном [min,max]; неизвестные значения передай null. Все оценки
помечаются ~. Не выдумывай цены, товары или ссылки на фото. Результат инструмента
выведи без изменений в блоке ```avelin-recipe\n{JSON}\n``` после короткого ответа.
Не дублируй ингредиенты текстом. Пользователь сам сохранит рецепт кнопкой
«Сформировать список». Инструмент только готовит карточку, ничего не сохраняет.
"""

def text(value, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Некорректное текстовое поле рецепта")
    return value.strip()

def integer(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or not 1 <= value <= maximum:
        raise ValueError("Некорректное количество")
    return int(value)

def build(db, title, servings, minutes, ingredients, steps, macros, **_):
    title = text(title, 160)
    servings, minutes = integer(servings, 20), integer(minutes, 1440)
    if not isinstance(ingredients, list) or not 1 <= len(ingredients) <= 30:
        raise ValueError("Нужен список ингредиентов")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        raise ValueError("Нужны шаги приготовления")
    steps = [text(step) for step in steps]
    if not isinstance(macros, dict):
        raise ValueError("Нужны КБЖУ на порцию")
    nutrition = {}
    for key in ("calories", "protein", "fat", "carbs"):
        value = macros.get(key)
        if value is None:
            nutrition[key] = None
        elif isinstance(value, list) and len(value) == 2 and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 10000 for n in value) and value[0] <= value[1]:
            nutrition[key] = value
        else:
            raise ValueError("КБЖУ передаётся диапазоном [min,max] или null")
    items, seen = [], set()
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.row_factory = sqlite3.Row
        for item in ingredients:
            name, store = text(item.get("name"), 500), text(item.get("store_name"), 100)
            if (store, name) in seen:
                raise ValueError("Объедини повторяющиеся товары")
            seen.add((store, name))
            row = conn.execute("SELECT name,store_name,package,price_rub,url,category FROM catalog_products WHERE name=? AND store_name=? AND recommendation_ready=1 ORDER BY rowid LIMIT 1", (name, store)).fetchone()
            if not row:
                raise ValueError(f"Товар отсутствует в каталоге: {name}")
            # Reuse the food filter used by the agent's product search.
            from agent_tools import search_store_products
            if not any(p["name"] == name for p in search_store_products([store], name, 50)):
                raise ValueError("В рецепт можно включить только продукты питания")
            price = row["price_rub"]
            if price is not None and (not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0):
                price = None
            items.append({"name": name, "store_name": store, "package": row["package"],
                          "price_rub": price, "amount": text(item.get("amount"), 160),
                          "packs": integer(item.get("packs", 1), 100), "url": row["url"]})
    card = {"title": title, "servings": servings, "minutes": minutes, "ingredients": items,
            "steps": steps, "macros": nutrition, "approximate": True,
            "total_rub": round(sum(i["price_rub"] * i["packs"] for i in items), 2) if all(i["price_rub"] is not None for i in items) else None}
    card["id"] = hashlib.sha256(json.dumps(card, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    return card

def ensure(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS saved_recipes(id TEXT PRIMARY KEY, card TEXT NOT NULL, checked TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL)")

def list_saved(db):
    with closing(sqlite3.connect(db)) as conn, conn:
        ensure(conn)
        return [{**json.loads(card), "checked": json.loads(checked), "created_at": created} for card, checked, created in conn.execute("SELECT card,checked,created_at FROM saved_recipes ORDER BY created_at DESC")]

def save(db, data):
    card = build(db, **data)
    with closing(sqlite3.connect(db)) as conn, conn:
        ensure(conn)
        conn.execute("INSERT OR IGNORE INTO saved_recipes(id,card,created_at) VALUES(?,?,?)", (card["id"], json.dumps(card, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    return card

def check(db, recipe_id, checked):
    with closing(sqlite3.connect(db)) as conn, conn:
        ensure(conn)
        row = conn.execute("SELECT card FROM saved_recipes WHERE id=?", (recipe_id,)).fetchone()
        if not row:
            raise ValueError("Рецепт не найден")
        count = len(json.loads(row[0])["ingredients"])
        if not isinstance(checked, list) or any(type(i) is not int or not 0 <= i < count for i in checked):
            raise ValueError("Некорректный список покупок")
        conn.execute("UPDATE saved_recipes SET checked=? WHERE id=?", (json.dumps(sorted(set(checked))), recipe_id))
    return {"ok": True}

SCHEMA = {"type": "function", "name": "build_recipe_card", "description": "Build a verified recipe card from exact catalog products. Does not save. Return result unchanged in an avelin-recipe fenced JSON block.", "parameters": {"type": "object", "properties": {
    "title": {"type": "string"}, "servings": {"type": "integer", "minimum": 1, "maximum": 20}, "minutes": {"type": "integer", "minimum": 1, "maximum": 1440},
    "ingredients": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "store_name": {"type": "string"}, "amount": {"type": "string", "description": "Amount used in the whole recipe, e.g. 200 г"}, "packs": {"type": "integer", "minimum": 1}}, "required": ["name", "store_name", "amount", "packs"]}},
    "steps": {"type": "array", "items": {"type": "string"}},
    "macros": {"type": "object", "description": "Approximate ranges per serving. Unknown = null.", "properties": {key: {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 2, "maxItems": 2} for key in ("calories", "protein", "fat", "carbs")}, "required": ["calories", "protein", "fat", "carbs"]}
}, "required": ["title", "servings", "minutes", "ingredients", "steps", "macros"]}}
