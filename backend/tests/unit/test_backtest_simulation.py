from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.backtest.simulation import metrics, simulate
from app.conditions.types import ConditionBar
from app.market_data.price_adjustment import DividendEvent
from app.rules.evaluation import RuleEvaluationService


def rule(condition="bollinger_mid_up", params=None):
    return SimpleNamespace(
        id=1,
        name="test",
        logic_operator="AND",
        conditions=[
            SimpleNamespace(
                condition_id=condition,
                params=params or {"period": 2, "slope_lookback": 1},
                sort_order=0,
            )
        ],
    )


def bars(values, volumes=None, opens=None):
    return [
        ConditionBar(
            date(2026, 1, 5) + timedelta(days=i),
            opens[i] if opens else value,
            max(opens[i] if opens else value, value) + 1,
            min(opens[i] if opens else value, value) - 1,
            value,
            volumes[i] if volumes else 100,
        )
        for i, value in enumerate(values)
    ]


def run(data, *, strategy=None, start=None, end=None, events=None):
    return simulate(
        strategy or rule(),
        "TEST",
        data,
        events or [],
        start or data[0].trade_date,
        end or data[-1].trade_date,
        [b.trade_date for b in data],
    )


def test_first_continued_invalidated_reentry_and_next_open_fills():
    data = bars([10, 10, 12, 14, 16, 8, 6, 10, 12], opens=[10, 10, 11, 13, 15, 9, 7, 9, 11])
    result = run(data)
    assert [s["state"] for s in result["signals"]] == [
        "first",
        "continued",
        "continued",
        "invalidated",
        "not_met",
        "reentered",
        "continued",
    ]
    assert len(result["trades"]) == 2  # No pyramiding on continued signals.
    closed, held = result["trades"]
    assert closed["entrySignalDate"] == data[2].trade_date.isoformat()
    assert closed["entryDate"] == data[3].trade_date.isoformat()
    assert closed["entryPrice"] == 13
    assert closed["exitDate"] == data[6].trade_date.isoformat()
    assert closed["exitPrice"] == 7
    assert closed["holdingDays"] == 3
    assert held["entryPrice"] == 11 and held["status"] == "open"
    assert held["unrealizedReturn"] == pytest.approx(12 / 11 - 1)
    assert result["metrics"]["tradeCount"] == 1


def test_suspension_zero_volume_invalid_open_delay_both_sides():
    data = bars(
        [10, 10, 12, 14, 15, 16, 8, 7, 6, 5],
        volumes=[100, 100, 100, 0, 100, 100, 100, 0, 100, 100],
        opens=[10, 10, 12, 14, 0, 16, 8, 7, 0, 5],
    )
    result = run(data)
    trade = result["trades"][0]
    assert trade["entryDate"] == data[5].trade_date.isoformat()
    assert trade["exitDate"] == data[9].trade_date.isoformat()
    assert trade["holdingDays"] == 4  # Exchange sessions include suspension days.


def test_pending_buy_and_pending_exit_are_not_realized():
    data = bars([10, 10, 12])
    result = run(data)
    assert result["trades"][0]["status"] == "unfilled"
    assert result["trades"][0]["entryPrice"] is None
    assert result["metrics"]["winRate"] is None
    result = run(bars([10, 10, 12, 14, 8]))
    assert result["trades"][0]["status"] == "open"
    assert result["trades"][0]["pendingSide"] == "sell"
    assert result["metrics"]["tradeCount"] == 0


def test_future_prices_and_dividends_do_not_change_past_signals():
    data = bars([10, 10, 12, 14, 16, 8, 6, 10, 12])
    cutoff = data[5].trade_date
    original = run(data, end=cutoff)
    changed = data[:6] + bars([10000, 20000, 30000])
    # Use the original future dates; their extreme values must never enter the prefix.
    changed = data[:6] + [
        ConditionBar(data[i].trade_date, 10000, 10001, 9999, 10000, 100) for i in range(6, 9)
    ]
    future_event = DividendEvent(data[7].trade_date, cash_dividend=2)
    assert run(changed, end=cutoff, events=[future_event]) == original
    full = run(data, events=[future_event])
    assert [s for s in full["signals"] if s["date"] <= cutoff.isoformat()] == original["signals"]


def test_dividend_adjustment_is_shared_formula_and_not_double_counted():
    # Raw ex-dividend decline should disappear in adjusted prices and preserve signal.
    data = bars([100, 100, 110, 120, 108, 120])
    event = DividendEvent(data[4].trade_date, cash_dividend=12)
    result = run(data, events=[event])
    trade = result["trades"][0]
    assert trade["entryPrice"] == pytest.approx(108)  # 120 * 0.9 on end-date basis
    assert trade["status"] == "open"
    assert trade["unrealizedReturn"] == pytest.approx(120 / 108 - 1)
    assert result["signals"][2]["state"] == "continued"


def test_monthly_engine_uses_only_month_to_date():
    data = [
        ConditionBar(date(2026, 1, 5), 10, 11, 9, 10, 100),
        ConditionBar(date(2026, 2, 5), 12, 13, 11, 12, 100),
        ConditionBar(date(2026, 3, 5), 14, 15, 13, 14, 100),
        ConditionBar(date(2026, 3, 20), 2, 3, 1, 2, 100),
    ]
    strategy = rule("macd_positive", {"short_period": 1, "long_period": 2, "signal_period": 1})
    result = run(data, strategy=strategy)
    early = RuleEvaluationService.evaluate_bars(strategy, "TEST", data[:3])
    assert result["signals"][1]["isMet"] == early.is_met
    assert early.is_met
    assert not result["signals"][-1]["isMet"]


def test_new_listing_actual_period_and_too_short_history():
    data = bars([10, 10, 12, 14])
    result = run(data, start=date(2023, 1, 1))
    assert result["actualStart"] == data[2].trade_date.isoformat()
    with pytest.raises(ValueError, match="歷史資料不足"):
        run(data[:2])


def test_metrics_compound_drawdown_factor_and_zero_trades():
    trades = [
        dict(status="closed", exitDate=f"2026-01-{i + 10}", entryDate="2026-01-01", returnRate=r)
        for i, r in enumerate([0.2, -0.1, -0.2, 0.1, 0])
    ]
    trades.append(dict(status="open", unrealizedReturn=10))
    result = metrics(trades)
    assert result["tradeCount"] == 5
    assert result["winRate"] == 0.4
    assert result["averageReturn"] == pytest.approx(0)
    assert result["compoundReturn"] == pytest.approx(1.2 * 0.9 * 0.8 * 1.1 - 1)
    assert result["maxDrawdown"] == pytest.approx(0.28)
    assert result["profitFactor"] == pytest.approx(1)
    assert result["insufficientSample"]
    assert not metrics(trades[:5] * 2)["insufficientSample"]
    assert metrics(trades[:1])["noLosses"]
    assert metrics([])["winRate"] is None
    assert metrics([])["compoundReturn"] is None
    assert not metrics([])["noLosses"]


def test_holiday_week_evaluates_once_on_last_session():
    dates = [date(2026, 10, d) for d in (19, 20, 21, 22, 27, 28, 29)]
    data = [replace(bar, trade_date=day) for bar, day in zip(bars([10] * 7), dates, strict=True)]
    strategy = rule()
    strategy.evaluation_frequency = "weekly"
    result = run(data, strategy=strategy)
    assert [signal["date"] for signal in result["signals"]] == ["2026-10-22"]
    assert result["actualEnd"] == "2026-10-22"
