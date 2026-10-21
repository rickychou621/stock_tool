import copy

import pytest

from app.backtest.service import definition_fingerprint, restore_rule
from app.watchlist.evaluation import fingerprint


def snapshot():
    return dict(
        id=1, name="戰法", logic_operator="AND", evaluation_frequency="daily",
        conditions=[
            dict(condition_id="ma_rising", params={"period": 20, "lookback": 5},
                 sort_order=0, role="premise"),
            dict(condition_id="price_touch_ma", params={"period": 20},
                 sort_order=1, role="entry"),
        ],
    )


@pytest.mark.parametrize("field", ["role", "evaluation_frequency", "params", "logic_operator",
                                   "sort_order", "condition_id"])
def test_definition_changes_invalidate_both_fingerprints(field):
    original = snapshot()
    changed = copy.deepcopy(original)
    if field == "evaluation_frequency":
        changed[field] = "weekly"
    elif field == "logic_operator":
        changed[field] = "OR"
    else:
        changed["conditions"][0][field] = {
            "role": "exit", "params": {"period": 30}, "sort_order": 3,
            "condition_id": "macd_positive",
        }[field]
    assert definition_fingerprint(original) != definition_fingerprint(changed)
    assert fingerprint(restore_rule(original)) != fingerprint(restore_rule(changed))


def test_irrelevant_fields_and_json_key_order_do_not_change_fingerprint():
    original = snapshot()
    changed = copy.deepcopy(original)
    changed.update(id=99, name="改名", is_enabled=False)
    changed["conditions"][0].update(id=123, params={"lookback": 5, "period": 20})
    changed["conditions"].reverse()
    assert definition_fingerprint(original) == definition_fingerprint(changed)
