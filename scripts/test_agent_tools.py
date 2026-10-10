from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import agent_tools


SCHEMA = """
CREATE TABLE daily_metrics (
  day TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL,
  selected_source TEXT NOT NULL, candidate_sources INTEGER NOT NULL,
  confidence TEXT NOT NULL, rule TEXT NOT NULL,
  PRIMARY KEY(day, metric)
);
CREATE TABLE user_profile (
  id INTEGER PRIMARY KEY, height_cm REAL, goal TEXT,
  calorie_target REAL, protein_target REAL, updated_at TEXT
);
CREATE TABLE body_measurements (
  id INTEGER PRIMARY KEY, measured_at TEXT, kind TEXT, value REAL, source TEXT
);
INSERT INTO user_profile VALUES(1,180,'maintain',2300,160,'2026-10-03');
"""


class SummaryToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db = agent_tools.DB
        agent_tools.DB = Path(self.temp_dir.name) / "test.db"
        conn = sqlite3.connect(agent_tools.DB)
        try:
            conn.executescript(SCHEMA)
            conn.executemany(
                "INSERT INTO daily_metrics VALUES(?,?,?,?,?,?,?,?)",
                [
                    ("2026-10-01", "body.weight", 82.0, "kg", "scale", 1, "high", "latest"),
                    ("2026-10-03", "body.weight", 81.5, "kg", "scale", 1, "high", "latest"),
                    ("2026-10-03", "nutrition.energy", 1800, "kcal", "food", 1, "high", "single"),
                    ("2026-10-03", "nutrition.protein", 120, "g", "food", 1, "high", "single"),
                    ("2026-10-03", "activity.steps", 8000, "count", "phone", 1, "high", "single"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        agent_tools.DB = self.old_db
        self.temp_dir.cleanup()

    def test_daily_summary_uses_profile_targets_and_preserves_missing_values(self) -> None:
        result = agent_tools.get_daily_summary("2026-10-03")
        self.assertEqual(result["nutrition"]["remaining"], {"calories": 500.0, "protein": 40.0})
        self.assertEqual(result["body"]["weightChange7dKg"], -0.5)
        self.assertIsNone(result["sleep"]["duration"])

    def test_period_summary_reports_recorded_day_coverage(self) -> None:
        result = agent_tools.get_period_summary(3, "2026-10-03")
        self.assertEqual(result["period"]["start"], "2026-10-01")
        self.assertEqual(result["body"]["weight"]["recordedDays"], 2)
        self.assertEqual(result["body"]["weight"]["coveragePercent"], 67)
        self.assertEqual(result["body"]["weight"]["change"], -0.5)

    def test_missing_day_is_not_reported_as_zero(self) -> None:
        result = agent_tools.get_daily_summary("2026-10-02")
        self.assertEqual(result["status"], "no_data")
        self.assertIsNone(result["nutrition"]["remaining"]["calories"])

    def test_invalid_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            agent_tools.get_daily_summary("03.10.2026")

    def test_new_tools_are_exposed_to_the_model(self) -> None:
        schema_names = {schema["name"] for schema in agent_tools.TOOL_SCHEMAS}
        self.assertIn("get_daily_summary", agent_tools.TOOLS)
        self.assertIn("get_period_summary", agent_tools.TOOLS)
        self.assertIn("get_daily_summary", schema_names)
        self.assertIn("get_period_summary", schema_names)


if __name__ == "__main__":
    unittest.main()
