import json
import re
import sqlite3
from contextlib import nullcontext
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backtest.service import restore_rule, rule_snapshot
from app.backtest.simulation import adjusted_bars
from app.market_data.price_adjustment import DividendEvent
from app.market_scan.service import chosen_rules
from app.rules.evaluation import RuleEvaluationService
from app.rules.frequency import is_evaluation_day, last_evaluation_day
from app.rules.models import WatchRule
from tests.unit.test_backtest_simulation import bars, rule, run


@pytest.mark.parametrize("offset", range(7))
@pytest.mark.parametrize("frequency", ["daily", "weekly"])
def test_evaluation_weekdays(offset, frequency):
    day = date(2026, 1, 5) + timedelta(days=offset)
    days = [date(2026, 1, d) for d in range(5, 10)]
    assert is_evaluation_day(day, frequency, days) == (frequency == "daily" or offset == 4)


def test_last_day_holiday_unsorted_future_and_empty():
    days = [date(2026, 1, d) for d in [23, 15, 9, 12, 10]]
    assert last_evaluation_day(date(2026, 1, 17), days, "weekly") == date(2026, 1, 15)
    assert last_evaluation_day(date(2026, 1, 17), days, "daily") == date(2026, 1, 15)
    assert last_evaluation_day(date(2026, 1, 8), days, "weekly") is None
    assert last_evaluation_day(date(2026, 1, 23), days, "weekly") == date(2026, 1, 23)
    assert last_evaluation_day(date(2026, 1, 17), [], "daily") is None


@pytest.mark.parametrize("value", ["monthly", "", None])
def test_model_rejects_invalid_frequency(value):
    with pytest.raises(ValueError, match="判斷頻率"):
        WatchRule(evaluation_frequency=value)


def test_all_snapshot_paths_and_legacy_research(monkeypatch):
    from app.research import rule_variants as research

    strategy = rule()
    strategy.evaluation_frequency = "weekly"
    strategy.conditions[0].role = "premise"
    selected, = chosen_rules(SimpleNamespace(scalars=lambda query: [strategy]))
    assert selected.evaluation_frequency == "weekly"
    assert selected.conditions[0].role == "premise"
    snapshot = rule_snapshot(selected)
    assert snapshot["evaluation_frequency"] == "weekly"
    assert restore_rule(snapshot).evaluation_frequency == "weekly"
    old = {k: v for k, v in snapshot.items() if k != "evaluation_frequency"}
    assert restore_rule(old).evaluation_frequency == "daily"
    assert "evaluation_frequency" not in old
    seen = []

    def simulate(copied, *args):
        seen.append(copied)
        return {"signals": [], "trades": [], "actualStart": "2026-01-09",
                "actualEnd": "2026-01-09"}

    monkeypatch.setattr(research, "load_data", lambda *args: ([], [], {}))
    monkeypatch.setattr(research, "simulate", simulate)
    result = research.process_stock(
        lambda: nullcontext(None), "TEST", selected,
        date(2026, 1, 9), date(2026, 1, 9), date(2026, 1, 1), [], "stock", None, {},
    )
    assert result["reason"] is None
    assert len(seen) == 2
    assert all(r.evaluation_frequency == "weekly" for r in seen)
    assert seen[1].conditions[0].params == {"period": 20}


def weekly_data():
    # Jan 16 is an exchange holiday; Jan 10 represents a Saturday session.
    return [replace(b, trade_date=date(2026, 1, d)) for b, d in zip(
        bars([10] * 20),
        [5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 19, 20, 21, 22, 23, 26, 27, 28, 29, 30],
        strict=True,
    )]


@pytest.mark.parametrize("explicit_roles", [False, True])
def test_weekly_signals_fills_prior_and_daily_prefix(monkeypatch, explicit_roles):
    data = weekly_data()
    # The last session is suspended, so that week cannot generate a signal.
    data = [replace(b, volume=0) if b.trade_date.day in (10, 12) else b for b in data]
    strategy = rule()
    strategy.evaluation_frequency = "weekly"
    event = DividendEvent(date(2026, 1, 14), cash_dividend=1)
    original = RuleEvaluationService.evaluate_bars
    seen = []

    def evaluate(r, ticker, prefix):
        day = prefix[-1].trade_date
        assert day.day in (15, 23, 30)
        seen.append(day)
        expected = [b for b in data if b.trade_date <= day and b.volume > 0]
        assert prefix == adjusted_bars(expected, [event] if day >= event.ex_dividend_date else [])
        result = original(r, ticker, prefix)
        met = day.day != 23
        return replace(
            result, is_met=met, premise_met=met,
            entry_triggered=met if explicit_roles else None,
            exit_triggered=not met if explicit_roles else None,
        )

    monkeypatch.setattr(RuleEvaluationService, "evaluate_bars", evaluate)
    result = run(data, strategy=strategy, events=[event])
    assert seen == [date(2026, 1, d) for d in (15, 23, 30)]
    assert [s["state"] for s in result["signals"]] == ["first", "invalidated", "reentered"]
    closed, pending = result["trades"]
    assert closed["entrySignalDate"] == "2026-01-15"
    assert closed["entryDate"] == "2026-01-19"
    assert closed["exitSignalDate"] == "2026-01-23"
    assert closed["exitDate"] == "2026-01-26"
    assert pending["entrySignalDate"] == "2026-01-30"
    assert pending["status"] == "unfilled"


def test_weekly_warmup_and_midrun_insufficient_only_on_evaluation_days(monkeypatch):
    strategy = rule(params={"period": 10, "slope_lookback": 1})
    strategy.evaluation_frequency = "weekly"
    data = weekly_data()
    result = run(data, strategy=strategy)
    assert result["actualStart"] == "2026-01-23"
    original = RuleEvaluationService.evaluate_bars

    def evaluate(r, ticker, prefix):
        assert prefix[-1].trade_date.day in (10, 15, 23, 30)
        result = original(r, ticker, prefix)
        if prefix[-1].trade_date.day == 30:
            result.condition_results[0].data_sufficient = False
        return result

    monkeypatch.setattr(RuleEvaluationService, "evaluate_bars", evaluate)
    with pytest.raises(ValueError, match="2026-01-30 回測途中資料不足"):
        run(data, strategy=strategy)


@pytest.mark.parametrize("explicit", [False, True])
def test_daily_matches_entire_pre_change_result(explicit):
    strategy = rule()
    if explicit:
        strategy.evaluation_frequency = "daily"
    result = run(bars([10, 10, 12, 14, 16, 8, 6, 10, 12],
                      opens=[10, 10, 11, 13, 15, 9, 7, 9, 11]), strategy=strategy)
    expected = Path(__file__).parent / "fixtures/daily_frequency_baseline.json"
    assert result == json.loads(expected.read_text())


def test_migration_repeatable_guard_and_only_rule_two_updated():
    sql = (Path(__file__).resolve().parents[3] / "mysql/init/018_rule_frequency.sql").read_text()
    assert "FROM information_schema.COLUMNS" in sql
    assert "TABLE_SCHEMA=DATABASE() AND TABLE_NAME='watch_rules'" in sql
    assert "COLUMN_NAME='evaluation_frequency'" in sql
    assert "IF(@has_frequency=0," in sql
    assert "'SELECT 1'" in sql
    assert "PREPARE migration_statement FROM @ddl;" in sql
    assert "EXECUTE migration_statement;" in sql
    assert "DEALLOCATE PREPARE migration_statement;" in sql
    ddl = re.search(r"'(ALTER TABLE .*?)',\s*'SELECT 1'", sql).group(1).replace("''", "'")
    updates = re.findall(r"UPDATE .*?;", sql)
    assert updates == ["UPDATE watch_rules SET evaluation_frequency='weekly' WHERE id=2;"]
    # Exercise the guarded DDL and DML on isolated SQLite; no MySQL connection.
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE watch_rules (id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO watch_rules VALUES (?)", [(1,), (2,), (3,)])
        for _ in range(2):
            columns = [r[1] for r in db.execute("PRAGMA table_info(watch_rules)")]
            if "evaluation_frequency" not in columns:
                db.execute(ddl)
            db.execute(updates[0])
            assert db.execute("SELECT * FROM watch_rules ORDER BY id").fetchall() == [
                (1, "daily"), (2, "weekly"), (3, "daily"),
            ]


def test_weekly_monthly_condition_uses_current_month_to_friday():
    data = [replace(b, trade_date=d) for b, d in zip(
        bars([10, 12, 14, 2, 3]),
        [date(2026, 1, 9), date(2026, 2, 6), date(2026, 3, 6),
         date(2026, 3, 20), date(2026, 3, 23)],
        strict=True,
    )]
    strategy = rule("macd_positive", {"short_period": 1, "long_period": 2, "signal_period": 1})
    strategy.evaluation_frequency = "weekly"
    result = run(data, strategy=strategy)
    early = RuleEvaluationService.evaluate_bars(strategy, "TEST", data[:3])
    signals = {s["date"]: s for s in result["signals"]}
    assert signals["2026-03-06"]["isMet"] == early.is_met is True
    assert signals["2026-03-20"]["isMet"] is False
    assert "2026-03-23" not in signals
    assert result["trades"][0]["exitDate"] == "2026-03-23"


def test_holiday_week_and_unfinished_current_week():
    days = [date(2026, 10, d) for d in (19, 20, 21, 22, 27, 28, 29)]
    assert last_evaluation_day(days[-1], iter(days), "weekly") == date(2026, 10, 22)
    assert is_evaluation_day(date(2026, 10, 22), "weekly", days)
    assert not is_evaluation_day(days[-1], "weekly", days)
    assert last_evaluation_day(days[3], days[:4], "weekly") is None
    days.append(date(2026, 10, 30))
    assert last_evaluation_day(days[-1], days, "weekly") == days[-1]
    assert is_evaluation_day(days[-1], "weekly", days)
    assert not is_evaluation_day(date(2026, 10, 29), "weekly", days)


def test_weekly_dates_across_iso_year_boundary():
    days = [date(2026, 12, 31), date(2027, 1, 4)]
    assert last_evaluation_day(days[-1], days, "weekly") == days[0]
