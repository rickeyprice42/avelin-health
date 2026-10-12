"""Read-only, deterministic tools intended for a future LLM tool-calling layer."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "avelin-health.db"

METRIC_GROUPS = {
    "body": ("body.weight", "body.fat_percentage", "body.lean_mass", "body.bmi"),
    "nutrition": ("nutrition.energy", "nutrition.protein", "nutrition.fat", "nutrition.carbs", "nutrition.fiber"),
    "activity": ("activity.steps", "activity.distance", "energy.active", "energy.basal"),
    "sleep": ("sleep.stage",),
    "heart": ("heart.resting_rate", "heart.rate", "heart.hrv"),
}

def _iso_day(value: str | None, *, fallback: str | None = None) -> str:
    candidate = value or fallback
    if not candidate:
        raise ValueError("No date is available")
    try:
        return date.fromisoformat(candidate).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("date must use YYYY-MM-DD format") from exc

def _profile(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT height_cm,goal,calorie_target,protein_target,updated_at FROM user_profile WHERE id=1"
    ).fetchone()
    return dict(row) if row else {}

def _metric_rows(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT day,metric,value,unit,selected_source,confidence
           FROM daily_metrics WHERE day BETWEEN ? AND ? ORDER BY day,metric""",
        (start, end),
    ).fetchall()

@contextmanager
def connect():
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def get_health_summary(days: int = 7) -> dict[str, Any]:
    days=max(1,min(days,90))
    with connect() as conn:
        rows=conn.execute("""SELECT metric,ROUND(AVG(value),1) average,MIN(value) minimum,MAX(value) maximum,
          MAX(day) last_day FROM daily_metrics WHERE day >= date((SELECT MAX(day) FROM daily_metrics), ?) GROUP BY metric""",(f"-{days-1} days",)).fetchall()
    return {"periodDays":days,"metrics":[dict(r) for r in rows]}

def get_daily_summary(date: str | None = None) -> dict[str, Any]:
    """Return a compact, deterministic summary for one calendar day."""
    with connect() as conn:
        latest = conn.execute("SELECT MAX(day) FROM daily_metrics").fetchone()[0]
        day = _iso_day(date, fallback=latest)
        rows = _metric_rows(conn, day, day)
        values = {row["metric"]: dict(row) for row in rows}
        profile = _profile(conn)
        weight_rows = conn.execute(
            """SELECT day,value FROM daily_metrics
               WHERE metric='body.weight' AND day BETWEEN date(?,'-6 days') AND ?
               ORDER BY day""",
            (day, day),
        ).fetchall()

    def item(metric: str) -> dict[str, Any] | None:
        row = values.get(metric)
        if not row:
            return None
        return {
            "value": row["value"], "unit": row["unit"],
            "source": row["selected_source"], "confidence": row["confidence"],
        }

    consumed = {
        "calories": item("nutrition.energy"),
        "protein": item("nutrition.protein"),
        "fat": item("nutrition.fat"),
        "carbs": item("nutrition.carbs"),
        "fiber": item("nutrition.fiber"),
    }
    calorie_target = profile.get("calorie_target")
    protein_target = profile.get("protein_target")
    calories = values.get("nutrition.energy", {}).get("value")
    protein = values.get("nutrition.protein", {}).get("value")
    remaining = {
        "calories": None if calorie_target is None or calories is None else round(max(0, calorie_target - calories), 1),
        "protein": None if protein_target is None or protein is None else round(max(0, protein_target - protein), 1),
    }
    weight_change = None
    if len(weight_rows) >= 2:
        weight_change = round(weight_rows[-1]["value"] - weight_rows[0]["value"], 2)

    present_groups = {
        group: sum(metric in values for metric in metrics)
        for group, metrics in METRIC_GROUPS.items()
    }
    return {
        "date": day,
        "status": "no_data" if not rows else "partial",
        "coverage": {"metricsPresent": len(rows), "groups": present_groups},
        "body": {
            "weight": item("body.weight"),
            "weightChange7dKg": weight_change,
            "bodyFatPercentage": item("body.fat_percentage"),
            "leanMass": item("body.lean_mass"),
            "bmi": item("body.bmi"),
        },
        "nutrition": {
            "consumed": consumed,
            "targets": {"calories": calorie_target, "protein": protein_target},
            "remaining": remaining,
        },
        "activity": {
            "steps": item("activity.steps"),
            "distance": item("activity.distance"),
            "activeEnergy": item("energy.active"),
            "basalEnergy": item("energy.basal"),
        },
        "sleep": {"duration": item("sleep.stage")},
        "heart": {
            "restingRate": item("heart.resting_rate"),
            "heartRate": item("heart.rate"),
            "hrv": item("heart.hrv"),
        },
        "workout": {"available": False, "reason": "workouts_not_imported"},
    }

def get_period_summary(days: int = 7, end_date: str | None = None) -> dict[str, Any]:
    """Summarize 1-90 calendar days while reporting missing-day coverage."""
    days = max(1, min(int(days), 90))
    with connect() as conn:
        latest = conn.execute("SELECT MAX(day) FROM daily_metrics").fetchone()[0]
        end = _iso_day(end_date, fallback=latest)
        start = (date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
        rows = _metric_rows(conn, start, end)
        profile = _profile(conn)

    by_metric: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_metric.setdefault(row["metric"], []).append(row)

    def aggregate(metric: str) -> dict[str, Any] | None:
        metric_rows = by_metric.get(metric, [])
        if not metric_rows:
            return None
        values = [row["value"] for row in metric_rows]
        return {
            "averageOnRecordedDays": round(sum(values) / len(values), 2),
            "minimum": round(min(values), 2),
            "maximum": round(max(values), 2),
            "latest": round(values[-1], 2),
            "unit": metric_rows[-1]["unit"],
            "recordedDays": len({row["day"] for row in metric_rows}),
            "coveragePercent": round(100 * len({row["day"] for row in metric_rows}) / days),
        }

    def body_trend(metric: str) -> dict[str, Any] | None:
        result = aggregate(metric)
        metric_rows = by_metric.get(metric, [])
        if result is not None:
            result["change"] = round(metric_rows[-1]["value"] - metric_rows[0]["value"], 2) if len(metric_rows) >= 2 else None
        return result

    return {
        "period": {"start": start, "end": end, "days": days},
        "coverage": {
            "daysWithAnyData": len({row["day"] for row in rows}),
            "totalDays": days,
            "note": "Averages use recorded days only; missing days are not treated as zero.",
        },
        "body": {name: body_trend(metric) for name, metric in {
            "weight": "body.weight", "bodyFatPercentage": "body.fat_percentage",
            "leanMass": "body.lean_mass", "bmi": "body.bmi",
        }.items()},
        "nutrition": {name: aggregate(metric) for name, metric in {
            "calories": "nutrition.energy", "protein": "nutrition.protein",
            "fat": "nutrition.fat", "carbs": "nutrition.carbs", "fiber": "nutrition.fiber",
        }.items()},
        "activity": {name: aggregate(metric) for name, metric in {
            "steps": "activity.steps", "distance": "activity.distance",
            "activeEnergy": "energy.active", "basalEnergy": "energy.basal",
        }.items()},
        "sleep": {"duration": aggregate("sleep.stage")},
        "heart": {
            "restingRate": aggregate("heart.resting_rate"),
            "heartRate": aggregate("heart.rate"),
            "hrv": aggregate("heart.hrv"),
        },
        "goals": {"calories": profile.get("calorie_target"), "protein": profile.get("protein_target")},
        "workouts": {"available": False, "reason": "workouts_not_imported"},
    }

def get_nutrition_gap(day: str, calorie_target: float, protein_target: float) -> dict[str, Any]:
    with connect() as conn:
        values={r["metric"]:r["value"] for r in conn.execute("SELECT metric,value FROM daily_metrics WHERE day=? AND metric LIKE 'nutrition.%'",(day,))}
    return {"day":day,"consumed":{"calories":values.get("nutrition.energy"),"protein":values.get("nutrition.protein")},
            "remaining":{"calories":max(0,calorie_target-values.get("nutrition.energy",0)),"protein":max(0,protein_target-values.get("nutrition.protein",0))}}

def search_store_products(stores: list[str], query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    limit=max(1,min(limit,50))
    marks=",".join("?" for _ in stores)
    if not marks: return []
    where=f"""recommendation_ready=1 AND store_name IN ({marks})
      AND lower(COALESCE(category,'')) NOT LIKE '%товары для животных%'
      AND lower(COALESCE(category,'')) NOT LIKE '%дом, кухня%'
      AND lower(COALESCE(category,'')) NOT LIKE '%алкоголь%'
      AND lower(COALESCE(category,'')) NOT LIKE '%мелочи возле кассы%'
      AND COALESCE(name,'') NOT LIKE '%корм%'
      AND COALESCE(name,'') NOT LIKE '%Корм%'
      AND COALESCE(name,'') NOT LIKE '%КОРМ%'
      AND lower(COALESCE(name,'')) NOT LIKE '%аперитив%'
      AND COALESCE(name,'') NOT LIKE '%Аперитив%'
      AND lower(COALESCE(name,'')) NOT LIKE '%водка%'
      AND COALESCE(name,'') NOT LIKE '%Водка%'
      AND lower(COALESCE(name,'')) NOT LIKE '%вино%'
      AND COALESCE(name,'') NOT LIKE '%Вино%'
      AND lower(COALESCE(name,'')) NOT LIKE '%коньяк%'
      AND COALESCE(name,'') NOT LIKE '%Коньяк%'
      AND lower(COALESCE(name,'')) NOT LIKE '%ликер%'
      AND lower(COALESCE(name,'')) NOT LIKE '%ликёр%'"""
    params:list[Any]=list(stores)
    if query.strip():
        where += " AND (name LIKE ? OR brand LIKE ? OR category LIKE ?)"
        params += [f"%{query.strip()}%"]*3
    sql=f"""SELECT store_name,name,brand,category,package,price_rub,url,protein,fat,carbs,calories,nutrition_basis,nutrition_source,
      CASE WHEN protein IS NOT NULL AND fat IS NOT NULL AND carbs IS NOT NULL AND calories IS NOT NULL AND nutrition_source IS NOT NULL THEN 'verified' ELSE 'unknown' END nutrition_status FROM catalog_products WHERE {where}
      ORDER BY store_name,name LIMIT ?"""
    params.append(limit)
    with connect() as conn: return [dict(r) for r in conn.execute(sql,params)]

def get_user_profile() -> dict[str, Any]:
    with connect() as conn:
        row=conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
        measurements=[dict(r) for r in conn.execute("SELECT measured_at,kind,value,source FROM body_measurements ORDER BY measured_at DESC LIMIT 20")]
    return {"profile":dict(row) if row else {},"bodyMeasurements":measurements}

def build_recipe_card(**kwargs):
    import recipes
    return recipes.build(DB, **kwargs)

TOOLS = {
    "build_recipe_card": {"description": "Prepare a catalog-backed recipe card", "call": build_recipe_card},
    "get_daily_summary": {"description":"Compact health summary for one calendar day.","call":get_daily_summary},
    "get_period_summary": {"description":"Health summary and data coverage for a 1-90 day period.","call":get_period_summary},
    "get_health_summary": {"description":"Aggregated health metrics; never raw unrestricted SQL.","call":get_health_summary},
    "get_nutrition_gap": {"description":"Consumed and remaining calories/protein for one day.","call":get_nutrition_gap},
    "search_store_products": {"description":"Available food products; nutrition may require a labeled approximate estimate.","call":search_store_products},
    "get_user_profile": {"description":"User-confirmed goals and manual measurements; never inferred values.","call":get_user_profile},
}

TOOL_SCHEMAS = [
    {"type":"function","name":"get_daily_summary","description":"Get a compact daily health summary. Missing values are returned as null, never as zero.","parameters":{"type":"object","properties":{"date":{"type":"string","format":"date","description":"Calendar date in YYYY-MM-DD. Defaults to the latest imported day."}},"required":[]}},
    {"type":"function","name":"get_period_summary","description":"Get body, nutrition, activity, sleep and heart aggregates with explicit data coverage.","parameters":{"type":"object","properties":{"days":{"type":"integer","minimum":1,"maximum":90},"end_date":{"type":"string","format":"date","description":"Inclusive period end in YYYY-MM-DD. Defaults to the latest imported day."}},"required":[]}},
    {"type":"function","name":"get_health_summary","description":"Get normalized health aggregates.","parameters":{"type":"object","properties":{"days":{"type":"integer","minimum":1,"maximum":90}},"required":[]}},
    {"type":"function","name":"get_nutrition_gap","description":"Calculate remaining calories and protein for a date using explicit user targets.","parameters":{"type":"object","properties":{"day":{"type":"string","format":"date"},"calorie_target":{"type":"number","exclusiveMinimum":0},"protein_target":{"type":"number","exclusiveMinimum":0}},"required":["day","calorie_target","protein_target"]}},
    {"type":"function","name":"search_store_products","description":"Search available products. Nutrition fields may be unknown; estimate them only as clearly labeled ranges.","parameters":{"type":"object","properties":{"stores":{"type":"array","items":{"type":"string"}},"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":50}},"required":["stores"]}},
    {"type":"function","name":"get_user_profile","description":"Read user-confirmed profile data and manual measurements.","parameters":{"type":"object","properties":{},"required":[]}},
]

from recipes import SCHEMA as RECIPE_SCHEMA
TOOL_SCHEMAS.append(RECIPE_SCHEMA)
