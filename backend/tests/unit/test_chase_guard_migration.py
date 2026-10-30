import json
import sqlite3
from pathlib import Path


def test_chase_guard_migration_preserves_choices_and_is_repeatable():
    sql = (Path(__file__).resolve().parents[3]
           / "mysql/init/025_rule2_chase_guard.sql").read_text()
    assert "SET NAMES utf8mb4;" in sql
    assert "START TRANSACTION;" in sql
    assert "COMMIT;" in sql
    sql = sql.replace("SET NAMES utf8mb4;", "").replace("START TRANSACTION;", "BEGIN;")
    with sqlite3.connect(":memory:") as db:
        db.create_function("JSON_CONTAINS_PATH", 3,
                           lambda value, mode, path: int(path[2:] in json.loads(value)))
        now = ["2026-10-30 01:00:00"]
        db.create_function("UTC_TIMESTAMP", 0, lambda: now[0])
        db.execute("CREATE TABLE watch_rules (id INTEGER PRIMARY KEY, updated_at TEXT)")
        db.execute(
            "CREATE TABLE watch_rule_conditions (rule_id INT, condition_id TEXT, params TEXT)"
        )
        expected = {}
        for condition, key, default in [
            ("ma_rising", "min_slope_pct", 0.005),
            ("ma_touch_rebound", "max_close_distance_pct", 0.03),
            ("custom", "other", None),
        ]:
            for params in [{"period": 20}, {key: None}, {key: 0.05}]:
                rule_id = len(expected) + 1
                changed = condition != "custom" and key not in params
                expected[rule_id] = (
                    {**params, **({key: default} if changed else {})},
                    now[0] if changed else "old",
                )
                db.execute("INSERT INTO watch_rules VALUES (?, 'old')", (rule_id,))
                db.execute("INSERT INTO watch_rule_conditions VALUES (?, ?, ?)",
                           (rule_id, condition, json.dumps(params)))
        db.commit()
        for _ in range(2):
            db.executescript(sql)
            actual = {
                rule_id: (json.loads(params), updated_at)
                for rule_id, params, updated_at in db.execute(
                    "SELECT r.id, c.params, r.updated_at FROM watch_rules r "
                    "JOIN watch_rule_conditions c ON c.rule_id = r.id"
                )
            }
            assert actual == expected
            now[0] = "2026-10-31 01:00:00"
