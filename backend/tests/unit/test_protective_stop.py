from types import SimpleNamespace

import pytest

from app.rules.evaluation import ConditionEvaluation
from app.rules.protective_stop import protective_stop


def result(*conditions):
    return SimpleNamespace(condition_results=list(conditions))


@pytest.mark.parametrize("kind,price,tick", [("stock", 57.3, 0.1), ("etf", 57.45, 0.05)])
def test_stop_uses_exit_ma_even_when_exit_not_triggered(kind, price, tick):
    evaluated = result(
        ConditionEvaluation("ma_rising", True, "", indicators={"ma": 999}),
        ConditionEvaluation(
            "close_below_ma_days", False, "", role="exit", indicators={"ma": 57.61, "close": 58.0}
        ),
    )
    assert protective_stop(evaluated, kind) == {
        "close": 58.0, "price": price, "ma": 57.61, "tick": tick, "ticks": 3, "buffer": 0.0,
    }


@pytest.mark.parametrize(
    "conditions",
    [
        [],
        [ConditionEvaluation("close_below_ma_days", True, "", indicators={"ma": 50})],
        [ConditionEvaluation("ma_rising", True, "", role="exit", indicators={"ma": 50})],
        [ConditionEvaluation("close_below_ma_days", False, "", role="exit")],
    ],
)
def test_no_eligible_ma_returns_none(conditions):
    assert protective_stop(result(*conditions), "stock") is None


@pytest.mark.parametrize(
    "kind,ma,buffer,price,tick",
    [
        ("stock", 100, 0.02, 97.7, 0.1),
        ("etf", 100, 0.02, 97.85, 0.05),
        # Buffered base 50.078 floors to 50; downward ticks cross the 50 tier.
        ("stock", 51.1, 0.02, 49.85, 0.1),
        ("stock", 100, 0, 99.7, 0.5),
        ("stock", 57.61, 0, 57.3, 0.1),
        ("etf", 57.61, 0, 57.45, 0.05),
    ],
)
def test_buffered_stop_uses_base_price_grid_and_preserves_ma(kind, ma, buffer, price, tick):
    evaluated = result(ConditionEvaluation(
        "close_below_ma_days", False, "", role="exit",
        indicators={"ma": ma, "close": 101, "buffer": buffer},
    ))
    assert protective_stop(evaluated, kind) == {
        "close": 101.0, "price": price, "ma": ma,
        "tick": tick, "ticks": 3, "buffer": buffer,
    }
