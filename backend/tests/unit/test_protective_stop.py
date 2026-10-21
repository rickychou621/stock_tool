from types import SimpleNamespace

import pytest

from app.rules.evaluation import ConditionEvaluation
from app.watchlist.protective_stop import protective_stop


def result(*conditions):
    return SimpleNamespace(condition_results=list(conditions))


@pytest.mark.parametrize("kind,price,tick", [("stock", 57.3, 0.1), ("etf", 57.45, 0.05)])
def test_stop_uses_exit_ma_even_when_exit_not_triggered(kind, price, tick):
    evaluated = result(
        ConditionEvaluation("ma_rising", True, "", indicators={"ma": 999}),
        ConditionEvaluation(
            "close_below_ma_days", False, "", role="exit", indicators={"ma": 57.61}
        ),
    )
    assert protective_stop(evaluated, kind) == {
        "price": price, "ma": 57.61, "tick": tick, "ticks": 3,
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
