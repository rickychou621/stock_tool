import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backtest.simulation import simulate
from app.conditions.registry import get_condition
from app.conditions.types import ConditionBar

MIGRATION = Path(__file__).resolve().parents[3] / "mysql/init/016_rule2_roles.sql"
EXPECTED = [
    ("ma_rising", {"period": 20, "slope_lookback": 5}, 0, "premise"),
    ("price_touch_ma", {"period": 20, "tolerance": 0.01}, 1, "entry"),
    ("close_below_ma_days", {"period": 20, "days": 2}, 2, "exit"),
]


def _statements():
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text())
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    assert statements.pop(0) == "SET NAMES utf8mb4"
    # The replacement must be atomic: a failed insert cannot leave strategy two half-replaced.
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
        CREATE TABLE condition_catalog (id TEXT PRIMARY KEY);
        CREATE TABLE watch_rule_conditions (
            rule_id INTEGER REFERENCES watch_rules(id),
            condition_id TEXT REFERENCES condition_catalog(id),
            params TEXT, sort_order INTEGER, role TEXT
        );
        INSERT INTO watch_rules VALUES (3, 'A+B組合監控', 'AND');
        INSERT INTO condition_catalog VALUES ('bollinger_mid_up');
        INSERT INTO watch_rule_conditions
        VALUES (3, 'bollinger_mid_up', '{"period":20}', 0, 'premise');
    """)
    connection.executemany(
        "INSERT INTO condition_catalog VALUES (?)", [(row[0],) for row in EXPECTED]
    )
    try:
        yield connection
    finally:
        connection.close()


def _apply(db):
    # SQLite supports the migration's DELETE, INSERT SELECT and JSON_OBJECT.
    # SET NAMES is MySQL-specific and is checked separately above.
    for statement in _statements():
        db.execute(statement)


def _conditions(db):
    return [
        (condition_id, json.loads(params), order, role)
        for condition_id, params, order, role in db.execute(
            "SELECT condition_id, params, sort_order, role "
            "FROM watch_rule_conditions WHERE rule_id = 1 ORDER BY sort_order"
        )
    ]


def test_sql_targets_only_rule_two_and_registered_roles():
    delete, *inserts = _statements()
    assert re.fullmatch(r"DELETE FROM watch_rule_conditions WHERE rule_id = 1", delete)
    assert len(inserts) == 3
    parsed = []
    for statement in inserts:
        match = re.fullmatch(
            r"INSERT INTO watch_rule_conditions "
            r"\(rule_id, condition_id, params, sort_order, role\)\s+"
            r"SELECT 1, '([^']+)', JSON_OBJECT\(([^)]+)\), (\d+), '([^']+)'\s+"
            r"FROM watch_rules WHERE id = 1",
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
        db.execute("INSERT INTO watch_rules VALUES (1, '戰法二：布林上軌區間', 'AND')")
        db.execute(
            "INSERT INTO watch_rule_conditions "
            "VALUES (1, 'bollinger_mid_up', '{\"period\":20}', 0, 'premise')"
        )
    rules_before = db.execute("SELECT * FROM watch_rules ORDER BY id").fetchall()
    others_before = db.execute(
        "SELECT * FROM watch_rule_conditions WHERE rule_id != 1"
    ).fetchall()
    for _ in range(2):
        _apply(db)
        assert _conditions(db) == (EXPECTED if seeded else [])
        assert db.execute("SELECT * FROM watch_rules ORDER BY id").fetchall() == rules_before
        assert db.execute(
            "SELECT * FROM watch_rule_conditions WHERE rule_id != 1"
        ).fetchall() == others_before


def test_migrated_rule_buys_after_touch_and_sells_after_two_below_ma_closes(db):
    db.execute("INSERT INTO watch_rules VALUES (1, '戰法二：布林上軌區間', 'AND')")
    _apply(db)
    strategy = SimpleNamespace(
        id=1,
        name="戰法二：布林上軌區間",
        logic_operator="AND",
        conditions=[
            SimpleNamespace(condition_id=cid, params=params, sort_order=order, role=role)
            for cid, params, order, role in _conditions(db)
        ],
    )
    # Day 24: rising MA, price still above it. Day 25: pullback touches MA.
    # Day 27: first close below MA. Day 28: second consecutive close below MA.
    closes = [100.0] * 20 + [110.0] * 5 + [104.0, 110.0, 100.0, 99.0, 98.0]
    data = []
    for i, close in enumerate(closes):
        opening = {26: 105.0, 29: 97.0}.get(i, close)
        data.append(ConditionBar(
            date(2026, 1, 1) + timedelta(days=i),
            opening, max(opening, close) + 1, min(opening, close) - 1, close, 1000,
        ))
    result = simulate(
        strategy, "TEST", data, [], data[0].trade_date, data[-1].trade_date,
        [bar.trade_date for bar in data],
    )
    signals = {signal["date"]: signal for signal in result["signals"]}
    before_touch = signals[data[24].trade_date.isoformat()]
    assert before_touch["premiseMet"] is True
    assert before_touch["entryTriggered"] is False
    assert signals[data[25].trade_date.isoformat()]["entryTriggered"] is True
    assert signals[data[27].trade_date.isoformat()]["exitTriggered"] is False
    assert signals[data[28].trade_date.isoformat()]["exitTriggered"] is True
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["status"] == "closed"
    assert trade["entrySignalDate"] == data[25].trade_date.isoformat()
    assert trade["entryDate"] == data[26].trade_date.isoformat()
    assert trade["entryPrice"] == 105.0
    assert trade["exitSignalDate"] == data[28].trade_date.isoformat()
    assert trade["exitDate"] == data[29].trade_date.isoformat()
    assert trade["exitPrice"] == 97.0
