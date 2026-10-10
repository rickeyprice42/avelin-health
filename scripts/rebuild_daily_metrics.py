"""Build trustworthy daily metrics without modifying imported Apple Health rows."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_priorities (
  metric TEXT NOT NULL, source_name TEXT NOT NULL, priority INTEGER NOT NULL,
  reason TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(metric, source_name)
);
CREATE TABLE IF NOT EXISTS daily_metrics (
  day TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL,
  selected_source TEXT NOT NULL, candidate_sources INTEGER NOT NULL,
  confidence TEXT NOT NULL, rule TEXT NOT NULL,
  PRIMARY KEY(day, metric)
);
CREATE INDEX IF NOT EXISTS idx_daily_metric_day ON daily_metrics(metric, day);
CREATE TABLE IF NOT EXISTS user_profile (
  id INTEGER PRIMARY KEY CHECK(id=1), height_cm REAL, goal TEXT,
  calorie_target REAL, protein_target REAL, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS body_measurements (
  id INTEGER PRIMARY KEY, measured_at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('waist_cm','biceps_cm')),
  value REAL NOT NULL CHECK(value > 0), source TEXT NOT NULL DEFAULT 'manual'
);
INSERT OR IGNORE INTO user_profile(id) VALUES(1);
"""

ADDITIVE = {
    "activity.steps", "activity.distance", "energy.active", "energy.basal",
    "nutrition.energy", "nutrition.protein", "nutrition.fat", "nutrition.carbs", "nutrition.fiber",
}
LATEST = {"body.weight", "body.fat_percentage", "body.lean_mass", "body.bmi"}

def source_score(metric: str, source: str, last_seen: str) -> tuple:
    name = source.casefold()
    if metric.startswith("nutrition."):
        family = 0 if "fatsecret" in name else 50
    elif metric == "sleep.stage" or metric.startswith("heart."):
        family = 0 if "fitness" in name else 30
    elif metric.startswith("body."):
        family = 0 if "xiaomi home" in name else 10 if "health" in name else 20
    else:
        family = 0 if "iphone" in name else 20 if "fitness" in name else 30 if "mi fit" in name else 80
    # Newer devices win inside the same family. ISO dates sort chronologically.
    return family, "".join(chr(255 - ord(c)) for c in last_seen), source

def rebuild(db_path: Path, summary_path: Path | None = None) -> dict:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    sources = conn.execute("SELECT metric,source_name,MAX(start_at) FROM samples GROUP BY metric,source_name").fetchall()
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for metric, source, last_seen in sources: grouped[metric].append((source, last_seen))

    conn.execute("DELETE FROM source_priorities")
    priorities: list[tuple] = []
    for metric, candidates in grouped.items():
        ordered = sorted(candidates, key=lambda x: source_score(metric, x[0], x[1]))
        for index, (source, _) in enumerate(ordered, 1):
            reason = "Предпочтительный источник" if index == 1 else "Резервный источник"
            priorities.append((metric, source, index * 10, reason, 1))
    conn.executemany("INSERT INTO source_priorities VALUES(?,?,?,?,?)", priorities)
    conn.execute("DELETE FROM daily_metrics")

    rows = conn.execute("""
      SELECT substr(s.start_at,1,10), s.metric, s.source_name, s.unit,
             SUM(CASE WHEN s.metric='sleep.stage'
               AND COALESCE(s.text_value,'') NOT LIKE '%Awake'
               AND COALESCE(s.text_value,'') NOT LIKE '%InBed'
               THEN (julianday(s.end_at)-julianday(s.start_at))*24.0
               WHEN s.metric!='sleep.stage' THEN COALESCE(s.value,0) ELSE 0 END),
             COUNT(*), p.priority
      FROM samples s JOIN source_priorities p
        ON p.metric=s.metric AND p.source_name=s.source_name AND p.enabled=1
      WHERE s.metric IN ({})
      GROUP BY 1,2,3,4
      ORDER BY 1,2,p.priority
    """.format(",".join("?" for _ in ADDITIVE | {"sleep.stage"})), tuple(ADDITIVE | {"sleep.stage"})).fetchall()

    per_day: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for row in rows: per_day[(row[0], row[1])].append(row)
    daily: list[tuple] = []
    for (day, metric), candidates in per_day.items():
        chosen = min(candidates, key=lambda r: r[6])
        count = len(candidates)
        confidence = "high" if count == 1 else "medium"
        rule = "single_source" if count == 1 else "source_priority"
        unit = "h" if metric == "sleep.stage" else chosen[3]
        daily.append((day, metric, round(chosen[4], 4), unit, chosen[2], count, confidence, rule))

    latest_rows = conn.execute("""
      SELECT substr(s.start_at,1,10),s.metric,s.value,s.unit,s.source_name,
             COUNT(*) OVER(PARTITION BY substr(s.start_at,1,10),s.metric),
             ROW_NUMBER() OVER(PARTITION BY substr(s.start_at,1,10),s.metric ORDER BY s.start_at DESC,p.priority)
      FROM samples s JOIN source_priorities p ON p.metric=s.metric AND p.source_name=s.source_name
      WHERE s.metric IN ({}) AND s.value IS NOT NULL
    """.format(",".join("?" for _ in LATEST)), tuple(LATEST)).fetchall()
    for day, metric, value, unit, source, candidates, row_number in latest_rows:
        if row_number == 1:
            daily.append((day, metric, value, unit, source, candidates, "high" if candidates == 1 else "medium", "latest_measurement"))

    conn.executemany("INSERT INTO daily_metrics VALUES(?,?,?,?,?,?,?,?)", daily)
    conn.commit()
    stats = {
        "days": conn.execute("SELECT COUNT(DISTINCT day) FROM daily_metrics").fetchone()[0],
        "rows": conn.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0],
        "resolvedOverlaps": conn.execute("SELECT COUNT(*) FROM daily_metrics WHERE candidate_sources>1").fetchone()[0],
        "priorities": [
            {"metric": m, "source": s, "priority": p, "reason": r}
            for m, s, p, r in conn.execute("SELECT metric,source_name,priority,reason FROM source_priorities ORDER BY metric,priority")
        ],
    }
    series = {}
    for metric in ("body.weight", "activity.steps", "energy.active", "nutrition.energy", "nutrition.protein"):
        series[metric] = [
            {"day": day, "value": round(value, 2), "unit": unit, "source": source}
            for day, value, unit, source in conn.execute(
                "SELECT day,value,unit,selected_source FROM daily_metrics WHERE metric=? ORDER BY day DESC LIMIT 30", (metric,)
            ).fetchall()[::-1]
        ]
    latest_nutrition_day = conn.execute("SELECT MAX(day) FROM daily_metrics WHERE metric='nutrition.energy'").fetchone()[0]
    latest_nutrition = {}
    if latest_nutrition_day:
        latest_nutrition = {
            metric.split(".")[-1]: {"value": round(value, 1), "unit": unit}
            for metric, value, unit in conn.execute(
                "SELECT metric,value,unit FROM daily_metrics WHERE day=? AND metric LIKE 'nutrition.%'", (latest_nutrition_day,)
            )
        }
        latest_nutrition["day"] = latest_nutrition_day
    profile_row = conn.execute("SELECT height_cm,goal,calorie_target,protein_target FROM user_profile WHERE id=1").fetchone()
    conn.close()
    if summary_path and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["aggregation"] = stats
        summary["series"] = series
        summary["latestNutrition"] = latest_nutrition
        summary["profile"] = {"heightCm": profile_row[0], "goal": profile_row[1], "calorieTarget": profile_row[2], "proteinTarget": profile_row[3]}
        issues = summary.get("quality", {}).get("issues", [])
        for issue in issues:
            if issue.get("title") == "Шаги поступают из нескольких источников":
                issue.update({
                    "severity": "good",
                    "title": "Пересечения источников разрешены",
                    "detail": f"Правила приоритета выбрали один источник в каждом дне; разрешено пересечений: {stats['resolvedOverlaps']}.",
                })
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/avelin-health.db"))
    parser.add_argument("--summary", type=Path, default=Path("public/data/health-summary.json"))
    args = parser.parse_args()
    print(json.dumps(rebuild(args.db, args.summary), ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
