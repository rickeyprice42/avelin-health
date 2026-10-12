"""Prepare browser queues and merge exact nutrition-card results into catalogues."""
from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from catalog_export import build_catalog_files, rewrite_catalog_files
from kuper_parser import read_existing


QUEUE_FORMAT = "nutrition-queue-v1"
BATCH_FORMAT = "nutrition-batch-v1"
CACHE_FORMAT = "nutrition-cache-v1"
CACHE_NAME = "КБЖУ кэш.json"
PARSER_VERSION = "nutrition-v2"
NUTRITION_FIELDS = (
    "белки", "жиры", "углеводы", "ккал", "кбжу_на", "источник_кбжу",
    "кбжу_статус", "кбжу_проверено_utc", "кбжу_парсер",
)


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _site_url(value):
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return "", ""
    host = parsed.hostname.casefold() if parsed.hostname else ""
    if host in {"sbermarket.ru", "www.sbermarket.ru", "kuper.ru", "www.kuper.ru"} and parsed.path.startswith("/products/"):
        return "kuper", urlunsplit(("https", "kuper.ru", parsed.path, "", ""))
    if host in {"fix-price.com", "www.fix-price.com"} and "/p-" in parsed.path:
        return "fixprice", urlunsplit(("https", "fix-price.com", parsed.path, "", ""))
    return "", ""


def _identity(row):
    return f"{row.get('магазин_id', '')}|{row.get('id', '')}"


def _has_nutrition(row):
    return all(str(row.get(field) or "").strip() != "" for field in ("белки", "жиры", "углеводы", "ккал"))


def nutrition_issue(data, require_current_parser=False):
    """Return a reason when a full nutrition set is unsafe for automated use."""
    if not _has_nutrition(data):
        return "неполный комплект КБЖУ"
    if require_current_parser and data.get("кбжу_парсер") != PARSER_VERSION:
        return "устаревшая версия парсера"
    values = {}
    for field in ("белки", "жиры", "углеводы", "ккал"):
        try:
            value = float(str(data.get(field)).replace(" ", "").replace(",", "."))
        except (TypeError, ValueError):
            return f"поле «{field}» не является числом"
        if not math.isfinite(value):
            return f"поле «{field}» не является конечным числом"
        values[field] = value

    protein, fat, carbs, kcal = (values[x] for x in ("белки", "жиры", "углеводы", "ккал"))
    if min(values.values()) < 0:
        return "отрицательное значение"
    if max(protein, fat, carbs) > 100:
        return "макронутриент превышает 100 г на 100 г продукта"
    if protein + fat + carbs > 105:
        return "сумма белков, жиров и углеводов превышает 105 г"
    if kcal > 1000:
        return "калорийность превышает 1000 ккал на 100 г"

    expected = 4 * protein + 9 * fat + 4 * carbs
    if expected <= 12 and kcal <= 12:
        return ""
    if expected <= 0:
        return "калорийность есть, но макронутриенты равны нулю"
    ratio = kcal / expected
    if 3.7 <= ratio <= 4.6:
        return "значение похоже на кДж, записанные как ккал"
    if abs(kcal - expected) > max(25, expected * 0.30):
        return "калорийность не согласуется с БЖУ"
    return ""


def _trusted_nutrition(row):
    if nutrition_issue(row):
        return False
    source = str(row.get("источник_кбжу") or "")
    if source.startswith("карточка ") and row.get("кбжу_парсер") != PARSER_VERSION:
        return False
    return True


def _load_cache(output_dir):
    path = Path(output_dir) / CACHE_NAME
    if not path.exists():
        return {"format": CACHE_FORMAT, "items": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"format": CACHE_FORMAT, "items": {}}
    if value.get("format") != CACHE_FORMAT or not isinstance(value.get("items"), dict):
        return {"format": CACHE_FORMAT, "items": {}}
    return value


def _save_cache(output_dir, cache):
    path = Path(output_dir) / CACHE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def _update_from_data(row, data):
    updated = {
        "магазин": row.get("магазин", ""),
        "магазин_id": row.get("магазин_id", ""),
        "id": row.get("id", ""),
        "название": row.get("название", ""),
        "белки": data.get("белки", ""),
        "жиры": data.get("жиры", ""),
        "углеводы": data.get("углеводы", ""),
        "ккал": data.get("ккал", ""),
        "кбжу_на": data.get("кбжу_на") or "100 г",
        "источник_кбжу": data.get("источник_кбжу", ""),
        "кбжу_статус": data.get("кбжу_статус") or "точные данные карточки",
        "кбжу_проверено_utc": data.get("кбжу_проверено_utc") or _now(),
        "кбжу_парсер": data.get("кбжу_парсер", ""),
    }
    if data.get("состав"):
        updated["состав"] = data["состав"]
    return updated


def quarantine_legacy_nutrition(output_dir):
    """Back up and clear browser nutrition captured before the strict v2 parser."""
    output_dir = Path(output_dir)
    rows = read_existing(output_dir / "Все магазины.csv")
    if not rows:
        return {"rows": 0, "cache_removed": 0, "backup": None, "report": None, "files": None}

    quarantined = []
    for row in rows:
        if not _has_nutrition(row):
            continue
        source = str(row.get("источник_кбжу") or "")
        issue = nutrition_issue(row)
        legacy_browser = source.startswith("карточка ") and row.get("кбжу_парсер") != PARSER_VERSION
        unsafe_browser = source.startswith("карточка ") and bool(issue)
        if not (legacy_browser or unsafe_browser):
            continue
        reason = "устаревший браузерный парсер" if legacy_browser else issue
        quarantined.append({
            "магазин": row.get("магазин", ""),
            "магазин_id": row.get("магазин_id", ""),
            "id": row.get("id", ""),
            "название": row.get("название", ""),
            "белки": row.get("белки", ""),
            "жиры": row.get("жиры", ""),
            "углеводы": row.get("углеводы", ""),
            "ккал": row.get("ккал", ""),
            "источник_кбжу": source,
            "причина": reason,
            "ссылка": row.get("ссылка", ""),
        })
        for field in NUTRITION_FIELDS:
            row[field] = ""
        row["кбжу_статус"] = f"карантин: {reason}"

    cache = _load_cache(output_dir)
    removed = 0
    for url in list(cache["items"]):
        value = cache["items"].get(url)
        site, _ = _site_url(url)
        if site in {"kuper", "fixprice"} and (
            not isinstance(value, dict)
            or value.get("кбжу_парсер") != PARSER_VERSION
            or bool(nutrition_issue(value))
        ):
            del cache["items"][url]
            removed += 1

    if not quarantined and not removed:
        return {"rows": 0, "cache_removed": 0, "backup": None, "report": None, "files": None}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = output_dir / f"Резервная копия КБЖУ {stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    for pattern in ("*.csv", "*.xlsx"):
        for path in output_dir.glob(pattern):
            if path.is_file():
                shutil.copy2(path, backup / path.name)
    cache_path = output_dir / CACHE_NAME
    if cache_path.exists():
        shutil.copy2(cache_path, backup / cache_path.name)

    report = output_dir / "КБЖУ карантин.csv"
    files = None
    if quarantined:
        with report.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(quarantined[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(quarantined)
        files = rewrite_catalog_files(rows, output_dir)
    _save_cache(output_dir, cache)
    return {
        "rows": len(quarantined),
        "cache_removed": removed,
        "backup": backup,
        "report": report if quarantined else None,
        "files": files,
    }


def prepare_nutrition_queues(output_dir, refresh=False, max_age_days=None):
    """Create deduplicated Kuper/Fix Price queues, applying cache hits first."""
    output_dir = Path(output_dir)
    quarantine = quarantine_legacy_nutrition(output_dir)
    combined = output_dir / "Все магазины.csv"
    rows = read_existing(combined)
    if not rows:
        raise ValueError("Общий каталог пуст. Сначала соберите и импортируйте товары магазинов.")
    cache = _load_cache(output_dir)
    cached_updates = []
    grouped = {"kuper": {}, "fixprice": {}}
    unsupported = 0
    already_filled = 0
    def fresh(row):
        if refresh or not _trusted_nutrition(row): return False
        if max_age_days is None: return True
        try:
            checked = datetime.fromisoformat(str(row.get("кбжу_проверено_utc") or "").replace("Z", "+00:00"))
            if checked.tzinfo is None: checked = checked.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc)-checked).total_seconds() <= max_age_days*86400
        except ValueError: return False

    for row in rows:
        if fresh(row):
            already_filled += 1
            continue
        site, url = _site_url(row.get("ссылка"))
        if not site:
            unsupported += 1
            continue
        cached = cache["items"].get(url)
        if isinstance(cached, dict) and fresh(cached):
            cached_updates.append(_update_from_data(row, cached))
            continue
        item = grouped[site].setdefault(url, {
            "url": url,
            "название": row.get("название", ""),
            "refs": [],
        })
        item["refs"].append({
            "магазин": row.get("магазин", ""),
            "магазин_id": row.get("магазин_id", ""),
            "id": row.get("id", ""),
        })

    files = None
    if cached_updates:
        files = build_catalog_files(cached_updates, output_dir)

    queue_paths = {}
    labels = {"kuper": "Kuper", "fixprice": "Fix Price"}
    for site, by_url in grouped.items():
        entries = list(by_url.values())
        path = output_dir / f"КБЖУ очередь {labels[site]}.json"
        payload = {
            "format": QUEUE_FORMAT,
            "site": site,
            "created_at": _now(),
            "entries": entries,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        queue_paths[site] = path

    return {
        "rows": len(rows),
        "already_filled": already_filled,
        "cached_applied": len(cached_updates),
        "unsupported": unsupported,
        "queues": {site: len(items) for site, items in grouped.items()},
        "queue_paths": queue_paths,
        "files": files,
        "quarantine": quarantine,
    }


def import_nutrition_results(paths, output_dir):
    """Merge one or more accumulated browser batches and update the cache."""
    output_dir = Path(output_dir)
    existing = read_existing(output_dir / "Все магазины.csv")
    if not existing:
        raise ValueError("Общий каталог пуст. Сначала импортируйте товары.")
    by_identity = {_identity(row): row for row in existing if row.get("id")}
    cache = _load_cache(output_dir)
    updates_by_identity = {}
    successes = 0
    skipped = 0
    rejected = 0
    rejection_reasons = {}
    remaining = 0

    for source in paths:
        path = Path(source)
        try:
            package = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Не удалось прочитать пакет КБЖУ {path}: {exc}") from exc
        if package.get("format") != BATCH_FORMAT or not isinstance(package.get("results"), list):
            raise ValueError(f"Файл {path.name} не является пакетом результатов КБЖУ.")
        remaining += len(package.get("remaining") or [])
        for result in package["results"]:
            if not isinstance(result, dict) or result.get("status") != "ok":
                skipped += 1
                continue
            data = result.get("data")
            refs = result.get("refs")
            url = str(result.get("url") or "")
            if not isinstance(data, dict) or not isinstance(refs, list):
                skipped += 1
                continue
            issue = nutrition_issue(data, require_current_parser=True)
            if issue:
                rejected += 1
                rejection_reasons[issue] = rejection_reasons.get(issue, 0) + 1
                continue
            normalized = dict(data)
            normalized["кбжу_проверено_utc"] = result.get("captured_at") or _now()
            cache["items"][url] = normalized
            for ref in refs:
                key = f"{ref.get('магазин_id', '')}|{ref.get('id', '')}"
                row = by_identity.get(key)
                if not row:
                    continue
                updates_by_identity[key] = _update_from_data(row, normalized)
            successes += 1

    if not updates_by_identity:
        reasons = "; ".join(f"{reason}: {count}" for reason, count in sorted(rejection_reasons.items()))
        suffix = f" Причины отклонения: {reasons}." if reasons else ""
        raise ValueError(
            "В выбранных пакетах нет безопасных КБЖУ от текущей версии парсера. "
            "Старые пакеты нужно пересобрать новой закладкой." + suffix
        )
    files = build_catalog_files(list(updates_by_identity.values()), output_dir)
    cache_path = _save_cache(output_dir, cache)
    return {
        "cards": successes,
        "rows_updated": len(updates_by_identity),
        "skipped": skipped,
        "rejected": rejected,
        "rejection_reasons": rejection_reasons,
        "remaining": remaining,
        "cache": cache_path,
        "files": files,
    }
