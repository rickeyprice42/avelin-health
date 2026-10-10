"""Streaming Apple Health importer for Avelin Health.

Only a deliberately small MVP whitelist is stored. The original XML remains the
source of truth; imported rows retain provenance and can be rebuilt at any time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import xml.etree.ElementTree as ET
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

METRICS = {
    "HKQuantityTypeIdentifierBodyMass": ("body.weight", "kg"),
    "HKQuantityTypeIdentifierBodyFatPercentage": ("body.fat_percentage", "%"),
    "HKQuantityTypeIdentifierLeanBodyMass": ("body.lean_mass", "kg"),
    "HKQuantityTypeIdentifierBodyMassIndex": ("body.bmi", "count"),
    "HKQuantityTypeIdentifierStepCount": ("activity.steps", "count"),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": ("activity.distance", "km"),
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("energy.active", "kcal"),
    "HKQuantityTypeIdentifierBasalEnergyBurned": ("energy.basal", "kcal"),
    "HKQuantityTypeIdentifierHeartRate": ("heart.rate", "bpm"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("heart.resting_rate", "bpm"),
    "HKQuantityTypeIdentifierDietaryEnergyConsumed": ("nutrition.energy", "kcal"),
    "HKQuantityTypeIdentifierDietaryProtein": ("nutrition.protein", "g"),
    "HKQuantityTypeIdentifierDietaryFatTotal": ("nutrition.fat", "g"),
    "HKQuantityTypeIdentifierDietaryCarbohydrates": ("nutrition.carbs", "g"),
    "HKQuantityTypeIdentifierDietaryFiber": ("nutrition.fiber", "g"),
    "HKCategoryTypeIdentifierSleepAnalysis": ("sleep.stage", "state"),
}

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS samples (
  id TEXT PRIMARY KEY, metric TEXT NOT NULL, value REAL, text_value TEXT,
  unit TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL,
  source_name TEXT NOT NULL, source_version TEXT, device TEXT,
  imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_metric_start ON samples(metric, start_at);
CREATE INDEX IF NOT EXISTS idx_samples_source ON samples(source_name);
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, file_size INTEGER NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT, records_seen INTEGER DEFAULT 0,
  records_stored INTEGER DEFAULT 0
);
"""

def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")

def stable_id(attrs: dict[str, str]) -> str:
    keys = ("type", "sourceName", "sourceVersion", "device", "unit", "value", "startDate", "endDate")
    return hashlib.sha256("\x1f".join(attrs.get(k, "") for k in keys).encode()).hexdigest()

def import_health(xml_path: Path, db_path: Path) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    cur = conn.execute("INSERT INTO imports(source_path,file_size,started_at) VALUES(?,?,?)", (str(xml_path), xml_path.stat().st_size, started))
    import_id = cur.lastrowid
    seen = selected = stored = workouts = 0
    sources: Counter[str] = Counter()
    min_date: datetime | None = None
    max_date: datetime | None = None
    latest: dict[str, tuple[datetime, float]] = {}
    daily: dict[str, Counter[str]] = {"activity.steps": Counter(), "energy.active": Counter()}
    sleep_by_day: Counter[str] = Counter()
    batch: list[tuple] = []

    for _, elem in ET.iterparse(xml_path, events=("end",)):
        if elem.tag == "Workout":
            workouts += 1
        elif elem.tag == "Record":
            seen += 1
            attrs = elem.attrib
            spec = METRICS.get(attrs.get("type", ""))
            if spec:
                selected += 1
                metric, canonical_unit = spec
                source = attrs.get("sourceName", "Unknown")
                sources[source] += 1
                try:
                    start = parse_date(attrs["startDate"])
                    end = parse_date(attrs["endDate"])
                except (KeyError, ValueError):
                    elem.clear(); continue
                min_date = start if min_date is None or start < min_date else min_date
                max_date = start if max_date is None or start > max_date else max_date
                raw = attrs.get("value", "")
                try: value = float(raw)
                except ValueError: value = None
                if metric == "body.fat_percentage" and value is not None and value <= 1:
                    value *= 100
                text_value = raw if value is None else None
                batch.append((stable_id(attrs), metric, value, text_value, canonical_unit,
                              start.isoformat(), end.isoformat(), source,
                              attrs.get("sourceVersion"), attrs.get("device"), started))
                if value is not None and metric in {"body.weight", "body.fat_percentage", "heart.resting_rate"}:
                    if metric not in latest or start > latest[metric][0]: latest[metric] = (start, value)
                if value is not None and metric in daily: daily[metric][start.date().isoformat()] += value
                if metric == "sleep.stage" and raw not in {"HKCategoryValueSleepAnalysisInBed", "HKCategoryValueSleepAnalysisAwake"}:
                    sleep_by_day[start.date().isoformat()] += max(0, (end-start).total_seconds()/3600)
                if len(batch) >= 2000:
                    before = conn.total_changes
                    conn.executemany("INSERT OR IGNORE INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)", batch)
                    stored += conn.total_changes - before
                    batch.clear()
        elem.clear()
    if batch:
        before = conn.total_changes
        conn.executemany("INSERT OR IGNORE INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)", batch)
        stored += conn.total_changes - before
    finished = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute("UPDATE imports SET finished_at=?,records_seen=?,records_stored=? WHERE id=?", (finished, seen, stored, import_id))
    conn.commit()
    total_sources = conn.execute("SELECT COUNT(DISTINCT source_name) FROM samples").fetchone()[0]
    total_rows = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    metric_rows = conn.execute("""
        SELECT metric, COUNT(*), COUNT(DISTINCT source_name), MIN(start_at), MAX(start_at)
        FROM samples GROUP BY metric ORDER BY COUNT(*) DESC
    """).fetchall()
    source_rows = conn.execute("""
        SELECT source_name, COUNT(*), COUNT(DISTINCT metric), MIN(start_at), MAX(start_at)
        FROM samples GROUP BY source_name ORDER BY COUNT(*) DESC
    """).fetchall()
    conn.close()

    anchor = max_date.date() if max_date else datetime.now().date()
    days = [(anchor - timedelta(days=i)).isoformat() for i in range(7)]
    average = lambda c: round(sum(c[d] for d in days) / 7, 1) if any(c[d] for d in days) else None
    metrics = [{"metric": r[0], "records": r[1], "sources": r[2], "start": r[3][:10], "end": r[4][:10]} for r in metric_rows]
    source_details = [{"name": r[0], "records": r[1], "metrics": r[2], "start": r[3][:10], "end": r[4][:10]} for r in source_rows]
    by_metric = {m["metric"]: m for m in metrics}
    issues = []
    step_sources = by_metric.get("activity.steps", {}).get("sources", 0)
    if step_sources > 1:
        issues.append({"severity": "warning", "title": "Шаги поступают из нескольких источников", "detail": f"Найдено источников: {step_sources}. До построения дневных итогов нужно задать приоритеты."})
    if average(sleep_by_day) is None:
        issues.append({"severity": "warning", "title": "Нет свежих данных о сне", "detail": "За последние 7 дней экспорта стадии сна не найдены."})
    body_count = by_metric.get("body.weight", {}).get("records", 0)
    if body_count < 14:
        issues.append({"severity": "info", "title": "Редкие измерения веса", "detail": f"В истории найдено {body_count} измерений — тренд будет предварительным."})
    issues.append({"severity": "good", "title": "Происхождение данных сохранено", "detail": "У каждой записи остаются приложение-источник, устройство и временной интервал."})
    return {
        "importedAt": finished,
        "period": {"start": min_date.date().isoformat() if min_date else "", "end": anchor.isoformat()},
        "totals": {"records": seen, "stored": total_rows, "workouts": workouts, "sources": total_sources},
        "latest": {
            "weightKg": latest.get("body.weight", (None, None))[1],
            "bodyFatPercent": latest.get("body.fat_percentage", (None, None))[1],
            "restingHeartRate": latest.get("heart.resting_rate", (None, None))[1],
        },
        "recent": {"steps7d": average(daily["activity.steps"]), "activeEnergy7d": average(daily["energy.active"]), "sleepHours7d": average(sleep_by_day)},
        "topSources": sources.most_common(10),
        "quality": {
            "selectedRecords": selected,
            "exactDuplicates": max(0, selected - total_rows),
            "metrics": metrics,
            "sources": source_details,
            "issues": issues,
        },
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("xml", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/avelin-health.db"))
    parser.add_argument("--summary", type=Path, default=Path("public/data/health-summary.json"))
    args = parser.parse_args()
    summary = import_health(args.xml, args.db)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    from rebuild_daily_metrics import rebuild
    rebuild(args.db, args.summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
