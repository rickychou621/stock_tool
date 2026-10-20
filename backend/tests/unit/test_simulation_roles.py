from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from app.rules.evaluation import RuleEvaluationService
from tests.unit.test_backtest_simulation import bars, run


def role_rule(*, entry=True, exit=True, premise_period=2):
    conditions = [
        ("ma_rising", "premise", {"period": premise_period, "slope_lookback": 1}),
    ]
    if entry:
        conditions.append(("price_touch_ma", "entry", {"period": 2, "tolerance": 0}))
    if exit:
        conditions.append(("close_below_ma_days", "exit", {"period": 2, "days": 2}))
    return SimpleNamespace(
        id=1,
        name="roles",
        logic_operator="AND",
        conditions=[
            SimpleNamespace(condition_id=cid, role=role, params=params, sort_order=i)
            for i, (cid, role, params) in enumerate(conditions)
        ],
    )


def test_explicit_exit_holds_through_failed_premise_and_fills_next_open():
    data = bars([10, 10, 12, 14, 12, 10, 9])
    strategy = role_rule()
    result = run(data, strategy=strategy)
    trade, = result["trades"]
    assert trade["entrySignalDate"] == data[2].trade_date.isoformat()
    assert trade["entryDate"] == data[3].trade_date.isoformat()
    assert trade["entryPrice"] == 14
    failed_premise = result["signals"][2]
    assert failed_premise["state"] == "invalidated"
    assert failed_premise["premiseMet"] is False
    assert failed_premise["exitTriggered"] is False
    assert trade["exitSignalDate"] == data[5].trade_date.isoformat()
    assert trade["exitDate"] == data[6].trade_date.isoformat()
    assert trade["exitPrice"] == 9
    assert trade["status"] == "closed"

    for signal in result["signals"]:
        prefix = [b for b in data if b.trade_date.isoformat() <= signal["date"]]
        evaluated = RuleEvaluationService.evaluate_bars(strategy, "TEST", prefix)
        assert signal["premiseMet"] == signal["isMet"] == evaluated.premise_met
        assert signal["entryTriggered"] == evaluated.entry_triggered
        assert signal["exitTriggered"] == evaluated.exit_triggered
        assert signal["conditions"] == [asdict(c) for c in evaluated.condition_results]


def test_reentry_while_premise_stays_true():
    data = bars([10, 10, 10, 10, 10, 20, 19, 18, 19, 20])
    data[5] = replace(data[5], low=14)
    result = run(data, strategy=role_rule(premise_period=5))
    assert all(s["premiseMet"] for s in result["signals"])
    assert [s["entryTriggered"] for s in result["signals"]] == [
        True, False, False, True, True,
    ]
    closed, held = result["trades"]
    assert closed["entrySignalDate"] == data[5].trade_date.isoformat()
    assert closed["entryDate"] == data[6].trade_date.isoformat()
    assert closed["exitSignalDate"] == data[7].trade_date.isoformat()
    assert closed["exitDate"] == data[8].trade_date.isoformat()
    assert held["entrySignalDate"] == data[8].trade_date.isoformat()
    assert held["entryDate"] == data[9].trade_date.isoformat()
    assert held["entryPrice"] == 20
    assert held["status"] == "open"


def test_exit_only_keeps_premise_transition_entry():
    data = bars([10, 10, 14, 16, 14, 12, 11])
    result = run(data, strategy=role_rule(entry=False))
    trade, = result["trades"]
    assert trade["entrySignalDate"] == data[2].trade_date.isoformat()
    assert trade["entryDate"] == data[3].trade_date.isoformat()
    assert trade["exitSignalDate"] == data[5].trade_date.isoformat()
    assert trade["exitDate"] == data[6].trade_date.isoformat()
    assert all(s["entryTriggered"] is None for s in result["signals"])


def test_exit_only_does_not_reenter_until_new_premise_transition():
    data = bars([10, 10, 10, 10, 10, 20, 19, 18, 19, 20])
    result = run(data, strategy=role_rule(entry=False, premise_period=5))
    assert all(s["premiseMet"] for s in result["signals"])
    trade, = result["trades"]
    assert trade["entrySignalDate"] == data[5].trade_date.isoformat()
    assert trade["exitDate"] == data[8].trade_date.isoformat()
    assert trade["status"] == "closed"


def test_entry_only_keeps_premise_invalidation_exit():
    data = bars([10, 10, 12, 14, 12, 10, 9])
    result = run(data, strategy=role_rule(exit=False))
    trade, = result["trades"]
    assert trade["entrySignalDate"] == data[2].trade_date.isoformat()
    assert trade["entryDate"] == data[3].trade_date.isoformat()
    assert trade["exitSignalDate"] == data[4].trade_date.isoformat()
    assert trade["exitDate"] == data[5].trade_date.isoformat()
    assert all(s["exitTriggered"] is None for s in result["signals"])


def test_entry_requires_both_premise_and_trigger():
    data = bars([10, 14, 12, 13, 14, 18, 19])
    result = run(data, strategy=role_rule())
    # A touch while the MA falls cannot buy; a rising MA without a touch cannot buy.
    assert result["signals"][1]["premiseMet"] is False
    assert result["signals"][1]["entryTriggered"] is True
    assert result["signals"][3]["premiseMet"] is True
    assert result["signals"][3]["entryTriggered"] is False
    trade, = result["trades"]
    assert trade["entrySignalDate"] == data[4].trade_date.isoformat()
    assert trade["entryDate"] == data[5].trade_date.isoformat()


@pytest.mark.parametrize("role", ["entry", "exit"])
def test_all_roles_must_finish_warmup(role):
    strategy = role_rule()
    next(c for c in strategy.conditions if c.role == role).params["period"] = 5
    data = bars([10, 11, 12, 13, 14, 15, 16])
    result = run(data, strategy=strategy)
    expected_start = 4 if role == "entry" else 5
    assert result["actualStart"] == data[expected_start].trade_date.isoformat()


def test_legacy_trades_and_signal_states_match_pre_change_snapshot():
    data = bars([10, 10, 12, 14, 16, 8, 6, 10, 12], opens=[10, 10, 11, 13, 15, 9, 7, 9, 11])
    result = run(data)
    # Captured from the existing simulation before introducing role-based orders.
    assert result["trades"] == [
        dict(
            ticker="TEST",
            entrySignalDate="2026-01-07", entryDate="2026-01-08", entryPrice=13.0,
            exitSignalDate="2026-01-10", exitDate="2026-01-11", exitPrice=7.0,
            status="closed", returnRate=-0.46153846153846156,
            unrealizedReturn=None, holdingDays=3, valuationDate=None, pendingSide=None,
        ),
        dict(
            ticker="TEST",
            entrySignalDate="2026-01-12", entryDate="2026-01-13", entryPrice=11.0,
            exitSignalDate=None, exitDate=None, exitPrice=None,
            status="open", returnRate=None, unrealizedReturn=0.09090909090909083,
            holdingDays=0, valuationDate="2026-01-13", pendingSide=None,
        ),
    ]
    assert [(s["state"], s["isMet"]) for s in result["signals"]] == [
        ("first", True),
        ("continued", True),
        ("continued", True),
        ("invalidated", False),
        ("not_met", False),
        ("reentered", True),
        ("continued", True),
    ]
    for signal in result["signals"]:
        assert signal["premiseMet"] == signal["isMet"]
        assert signal["entryTriggered"] is None
        assert signal["exitTriggered"] is None
