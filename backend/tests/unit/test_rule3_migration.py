import json
import re
import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backtest.simulation import simulate
from app.conditions.registry import get_condition
from app.conditions.types import ConditionBar

MIGRATION = Path(__file__).resolve().parents[3] / "mysql/init/017_rule3_roles.sql"
EXPECTED = [
    ("macd_positive", {}, 0, "premise"),
    ("kd_golden_cross", {}, 1, "entry"),
    ("kd_high_death_cross", {"period": 9, "threshold": 70}, 2, "exit"),
    ("macd_negative_any", {}, 3, "exit"),
]


def _statements():
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text())
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    assert statements.pop(0) == "SET NAMES utf8mb4"
    # The replacement must be atomic: a failed insert cannot leave strategy three half-replaced.
    assert statements.pop(0) == "START TRANSACTION"
    assert statements.pop() == "COMMIT"
    return statements


@pytest.fixture
def db():
    # Only an isolated in-memory database; foreign keys exercise the missing-seed guard.
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE watch_rules (id INTEGER PRIMARY KEY, name TEXT, logic_operator TEXT);
        CREATE TABLE condition_catalog (
            id TEXT PRIMARY KEY, name TEXT, description TEXT, required_timeframe TEXT,
            update_frequency TEXT, param_schema TEXT
        );
        CREATE TABLE watch_rule_conditions (
            rule_id INTEGER REFERENCES watch_rules(id),
            condition_id TEXT REFERENCES condition_catalog(id),
            params TEXT, sort_order INTEGER, role TEXT
        );
        INSERT INTO watch_rules VALUES (3, 'A+B組合監控', 'AND'), (1, '戰法二', 'AND');
        INSERT INTO condition_catalog (id) VALUES ('bollinger_mid_up');
        INSERT INTO watch_rule_conditions
        VALUES (3, 'bollinger_mid_up', '{"period":20}', 0, 'premise'),
               (1, 'bollinger_mid_up', '{}', 0, 'premise');
    """)
    connection.executemany(
        "INSERT INTO condition_catalog (id) VALUES (?)", [(row[0],) for row in EXPECTED[:2]]
    )
    try:
        yield connection
    finally:
        connection.close()


def _apply(db):
    # SQLite supports the migration's DELETE, INSERT SELECT and JSON_OBJECT.
    # SET NAMES is MySQL-specific and is checked separately above.
    for statement in _statements():
        # Translate only MySQL's upsert syntax; execute the actual INSERT payload.
        statement = statement.replace("ON DUPLICATE KEY UPDATE", "ON CONFLICT(id) DO UPDATE SET")
        statement = re.sub(r"VALUES\((\w+)\)", r"excluded.\1", statement)
        db.execute(statement)


def _conditions(db):
    return [
        (condition_id, json.loads(params), order, role)
        for condition_id, params, order, role in db.execute(
            "SELECT condition_id, params, sort_order, role "
            "FROM watch_rule_conditions WHERE rule_id = 2 ORDER BY sort_order"
        )
    ]


def test_sql_targets_only_rule_three_and_registered_roles():
    catalog, delete, *inserts = _statements()
    assert catalog.startswith("INSERT INTO condition_catalog ")
    assert "ON DUPLICATE KEY UPDATE" in catalog
    assert re.fullmatch(r"DELETE FROM watch_rule_conditions WHERE rule_id = 2", delete)
    assert len(inserts) == 4
    parsed = []
    for statement in inserts:
        match = re.fullmatch(
            r"INSERT INTO watch_rule_conditions "
            r"\(rule_id, condition_id, params, sort_order, role\)\s+"
            r"SELECT 2, '([^']+)', JSON_OBJECT\(([^)]*)\), (\d+), '([^']+)'\s+"
            r"FROM watch_rules WHERE id = 2",
            statement,
        )
        assert match is not None
        condition_id, _, order, role = match.groups()
        assert get_condition(condition_id) is not None
        assert role in {"premise", "entry", "exit"}
        parsed.append((condition_id, int(order), role))
    assert parsed == [(cid, order, role) for cid, _, order, role in EXPECTED]


@pytest.mark.parametrize("seeded", [False, True])
def test_repeatable_replacement_preserves_other_rules_and_handles_missing_seed(db, seeded):
    if seeded:
        db.execute("INSERT INTO watch_rules VALUES (2, '戰法三：長波佈局', 'AND')")
        db.execute(
            "INSERT INTO watch_rule_conditions "
            "VALUES (2, 'bollinger_mid_up', '{\"period\":20}', 0, 'premise')"
        )
    rules_before = db.execute("SELECT * FROM watch_rules ORDER BY id").fetchall()
    others_before = db.execute(
        "SELECT * FROM watch_rule_conditions WHERE rule_id != 2"
    ).fetchall()
    for _ in range(2):
        _apply(db)
        catalog = db.execute(
            "SELECT id, required_timeframe, update_frequency FROM condition_catalog "
            "WHERE id IN ('kd_high_death_cross', 'macd_negative_any') ORDER BY id"
        ).fetchall()
        assert catalog == [(cid, "月K", "monthly") for cid in
                           ("kd_high_death_cross", "macd_negative_any")]
        assert _conditions(db) == (EXPECTED if seeded else [])
        assert db.execute("SELECT * FROM watch_rules ORDER BY id").fetchall() == rules_before
        assert db.execute(
            "SELECT * FROM watch_rule_conditions WHERE rule_id != 2"
        ).fetchall() == others_before



@pytest.mark.parametrize("exit_kind", ["kd_high_death_cross", "macd_negative_any"])
def test_migrated_rule_simulates_monthly_entry_and_each_exit(db, exit_kind):
    db.execute("INSERT INTO watch_rules VALUES (2, '戰法三：長波佈局', 'AND')")
    _apply(db)
    rule = SimpleNamespace(
        id=2, name="戰法三：長波佈局", logic_operator="AND",
        conditions=[
            SimpleNamespace(condition_id=cid, params=params, sort_order=order, role=role)
            for cid, params, order, role in _conditions(db)
        ],
    )
    closes = [40 + i for i in range(30)] + [75, 70, 80, 90, 100, 110, 70, 60]
    if exit_kind == "macd_negative_any":
        closes = [40 + i for i in range(30)] + [50, 50, 80, 90, 100, 110, 10, 10, 10]
    # Two daily bars per month exercise resampling and next-session execution.
    # Wide monthly ranges keep KD below 70 in the MACD-only exit scenario.
    bars = [
        ConditionBar(
            date(2020 + i // 12, i % 12 + 1, day), close,
            close + 1 if exit_kind == "kd_high_death_cross" else 200,
            close - 1 if exit_kind == "kd_high_death_cross" else 1,
            close, 1000,
        )
        for i, close in enumerate(closes) for day in (1, 2)
    ]
    result = simulate(
        rule, "TEST", bars, [], bars[0].trade_date, bars[-1].trade_date,
        [bar.trade_date for bar in bars],
    )
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["status"] == "closed"
    signals = {signal["date"]: signal for signal in result["signals"]}
    entry = signals[trade["entrySignalDate"]]
    assert entry["premiseMet"] is True
    assert entry["entryTriggered"] is True
    by_id = {c["condition_id"]: c for c in entry["conditions"]}
    assert by_id["macd_positive"]["is_met"] is True
    assert by_id["kd_golden_cross"]["is_met"] is True
    exit_signal = signals[trade["exitSignalDate"]]
    assert exit_signal["exitTriggered"] is True
    exits = {c["condition_id"]: c["is_met"] for c in exit_signal["conditions"]}
    assert exits[exit_kind] is True
    other_exit = (
        "macd_negative_any" if exit_kind == "kd_high_death_cross" else "kd_high_death_cross"
    )
    assert exits[other_exit] is False
    for side in ("entry", "exit"):
        signal_day = date.fromisoformat(trade[f"{side}SignalDate"])
        index = [bar.trade_date for bar in bars].index(signal_day)
        assert trade[f"{side}Date"] == bars[index + 1].trade_date.isoformat()
        assert trade[f"{side}Price"] == bars[index + 1].open
    if exit_kind == "kd_high_death_cross":
        assert trade["entrySignalDate"] == "2022-10-01"
        assert trade["exitSignalDate"] == "2023-01-01"
    else:
        assert trade["entrySignalDate"] == "2022-09-01"
        assert trade["exitSignalDate"] == "2023-02-01"


@pytest.mark.parametrize("seeded", [False, True])
def test_rule_params_v2_repeatable_and_scoped(db, seeded):
    db.execute("ALTER TABLE watch_rules ADD COLUMN updated_at TEXT")
    db.create_function("UTC_TIMESTAMP", 0, lambda: "2026-10-29 01:00:00")
    schemas = {
        "ma_touch_rebound": {"period": "int", "tolerance": "float"},
        "ma_rising": {"period": "int", "slope_lookback": "int"},
        "kd_golden_cross": {},
        "close_below_ma_days": {"period": "int", "days": "int"},
    }
    for cid, schema in schemas.items():
        db.execute("INSERT OR IGNORE INTO condition_catalog (id) VALUES (?)", (cid,))
        db.execute("UPDATE condition_catalog SET param_schema = ? WHERE id = ?",
                   (json.dumps(schema), cid))
    for cid, params in [
        ("ma_touch_rebound", {"period": 20, "tolerance": 0.01}),
        ("ma_rising", {"period": 20, "slope_lookback": 5}),
        ("kd_golden_cross", {}),
    ]:
        db.execute("INSERT INTO watch_rule_conditions VALUES (1, ?, ?, 1, 'entry')",
                   (cid, json.dumps(params)))
    if seeded:
        db.execute("INSERT INTO watch_rules (id, name) VALUES (2, '戰法三')")
        _apply(db)
    before = db.execute(
        "SELECT * FROM watch_rule_conditions WHERE rule_id != 2 "
        "OR condition_id != 'kd_golden_cross'"
    ).fetchall()
    other_rules = db.execute("SELECT * FROM watch_rules WHERE id != 2").fetchall()
    sql = re.sub(r"--[^\n]*", "", MIGRATION.with_name("023_rule_params_v2.sql").read_text())
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    assert statements.pop(0) == "SET NAMES utf8mb4"
    assert statements.pop(0) == "START TRANSACTION"
    assert statements.pop() == "COMMIT"
    for _ in range(2):
        for statement in statements:
            db.execute(statement)
        expected = {
            "ma_touch_rebound": {**schemas["ma_touch_rebound"], "max_close_distance_pct": "float"},
            "ma_rising": {**schemas["ma_rising"], "min_slope_pct": "float"},
            "kd_golden_cross": {"period": "int", "max_k_at_cross": "float"},
            "close_below_ma_days": {**schemas["close_below_ma_days"], "buffer": "float"},
        }
        for cid, schema in expected.items():
            actual = db.execute(
                "SELECT param_schema FROM condition_catalog WHERE id = ?", (cid,)
            ).fetchone()[0]
            assert json.loads(actual) == schema
        assert db.execute(
            "SELECT * FROM watch_rule_conditions WHERE rule_id != 2 "
            "OR condition_id != 'kd_golden_cross'"
        ).fetchall() == before
        assert db.execute("SELECT * FROM watch_rules WHERE id != 2").fetchall() == other_rules
        target = db.execute(
            "SELECT params FROM watch_rule_conditions "
            "WHERE rule_id = 2 AND condition_id = 'kd_golden_cross'"
        ).fetchall()
        assert [json.loads(row[0]) for row in target] == (
            [{"period": 9, "max_k_at_cross": 70}] if seeded else []
        )
        if seeded:
            assert db.execute(
                "SELECT updated_at FROM watch_rules WHERE id = 2"
            ).fetchone()[0] == "2026-10-29 01:00:00"
