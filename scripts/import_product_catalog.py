"""Import the existing store CSV catalog into Avelin's local SQLite database."""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_products (
  store_id TEXT NOT NULL, product_id TEXT NOT NULL, store_name TEXT NOT NULL,
  category TEXT, name TEXT NOT NULL, brand TEXT, package TEXT,
  price_rub REAL, url TEXT, available INTEGER NOT NULL DEFAULT 0,
  protein REAL, fat REAL, carbs REAL, calories REAL, nutrition_basis TEXT,
  nutrition_source TEXT, nutrition_status TEXT, ingredients TEXT,
  enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT,
  recommendation_ready INTEGER NOT NULL DEFAULT 0, quality_issue TEXT,
  PRIMARY KEY(store_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_catalog_store ON catalog_products(store_name, available);
CREATE INDEX IF NOT EXISTS idx_catalog_macros ON catalog_products(protein, calories);
"""

def number(value: str | None) -> float | None:
    if not value or not value.strip(): return None
    try: return float(value.strip().replace(",", "."))
    except ValueError: return None

def truthy(value: str | None) -> int:
    return int((value or "").strip().casefold() in {"1", "true", "да", "yes"})

def nutrition_quality(row: dict[str, str]) -> tuple[int, str | None]:
    values = [number(row.get(k)) for k in ("белки", "жиры", "углеводы", "ккал")]
    protein, fat, carbs, calories = values
    if any(v is None for v in values): return 0, "КБЖУ заполнено не полностью"
    if any(v < 0 for v in values) or any(v > 100 for v in (protein, fat, carbs)): return 0, "КБЖУ вне допустимого диапазона"
    if protein + fat + carbs > 105: return 0, "Сумма макронутриентов превышает 100 г"
    if "проверить" in (row.get("кбжу_статус") or "").casefold(): return 0, "Источник пометил КБЖУ для проверки"
    if calories > 950: return 0, "Калорийность вне допустимого диапазона"
    if calories < 1 and max(protein, fat, carbs) < 0.1: return 0, "Подозрительно малые значения КБЖУ"
    estimated = protein * 4 + carbs * 4 + fat * 9
    if estimated > 10 and (calories < estimated * .55 or calories > estimated * 1.6):
        return 0, "КБЖУ не согласуется с калорийностью"
    return 1, None

def import_catalog(csv_path: Path, db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    read = ready = flagged = 0
    stores: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            read += 1
            store = row.get("магазин", "").strip()
            stores.add(store)
            allowed = truthy(row.get("использовать") or "да")
            available = truthy(row.get("доступность"))
            # Source macros are intentionally ignored while the catalog is rebuilt.
            # Availability controls discovery; nutrition is estimated separately and
            # must never masquerade as a verified source value.
            issue = "КБЖУ ожидает подтверждения или примерной оценки"
            recommendation_ready = int(bool(allowed and available))
            ready += recommendation_ready
            flagged += int(issue is not None)
            conn.execute("""INSERT INTO catalog_products VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(store_id,product_id) DO UPDATE SET
              category=excluded.category,name=excluded.name,brand=excluded.brand,package=excluded.package,
              price_rub=excluded.price_rub,url=excluded.url,available=excluded.available,protein=excluded.protein,
              fat=excluded.fat,carbs=excluded.carbs,calories=excluded.calories,nutrition_basis=excluded.nutrition_basis,
              nutrition_source=excluded.nutrition_source,nutrition_status=excluded.nutrition_status,
              ingredients=excluded.ingredients,enabled=excluded.enabled,updated_at=excluded.updated_at,
              recommendation_ready=excluded.recommendation_ready,quality_issue=excluded.quality_issue""", (
                row.get("магазин_id", ""), row.get("id", ""), store, row.get("категория"), row.get("название", ""),
                row.get("бренд"), row.get("фасовка"), number(row.get("цена_руб")), row.get("ссылка"), available,
                None, None, None, None,
                None, None, "ожидает оценки", row.get("состав"), allowed,
                row.get("обновлено_utc"), recommendation_ready, issue,
            ))
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM catalog_products").fetchone()[0]
    stats = {"read": read, "stored": total, "availableToAgent": ready, "awaitingNutrition": flagged, "stores": sorted(stores)}
    conn.close()
    return stats

def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/avelin-health.db"))
    parser.add_argument("--summary", type=Path, default=Path("public/data/catalog-summary.json"))
    args=parser.parse_args()
    stats=import_catalog(args.csv,args.db)
    args.summary.parent.mkdir(parents=True,exist_ok=True)
    args.summary.write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(stats,ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
