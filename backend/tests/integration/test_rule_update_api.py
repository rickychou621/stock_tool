from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.conditions.models import ConditionCatalog
from app.conditions.router import router as conditions_router
from app.core.dependencies import get_db
from app.rules.models import WatchRule, WatchRuleCondition
from app.rules.router import router


@pytest.fixture
def setup():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in (ConditionCatalog, WatchRule, WatchRuleCondition):
        model.__table__.create(engine)
    app = FastAPI()
    app.include_router(router)
    app.include_router(conditions_router)
    with Session(engine) as db:
        db.add(ConditionCatalog(
            id="ma_rising", name="月線", required_timeframe="daily", update_frequency="daily",
            param_schema={"period": "int", "slope_lookback": "int", "min_slope_pct": "float"},
        ))
        db.add(ConditionCatalog(
            id="custom", name="自訂", required_timeframe="daily", update_frequency="daily",
            param_schema={"signal_period": "int", "ratio": "float"},
        ))
        rule = WatchRule(name="原名", logic_operator="AND", updated_at=datetime(2020, 1, 1))
        rule.conditions = [
            WatchRuleCondition(condition_id="custom", params={}, sort_order=1, role="exit"),
            WatchRuleCondition(
                condition_id="ma_rising", params={"period": 20, "min_slope_pct": .01},
                               sort_order=0, role="premise"),
        ]
        db.add(rule)
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db, rule
    engine.dispose()


def payload(params=None):
    return {"name": "新名", "conditions": [
        {"conditionId": "ma_rising", "params": params if params is not None else {"period": 30}},
        {"conditionId": "custom", "params": {"signal_period": 5, "ratio": 0}},
    ]}


def test_update_preserves_identity_roles_and_updates_timestamp(setup):
    client, db, rule = setup
    ids = {c.condition_id: c.id for c in rule.conditions}
    response = client.put(f"/rules/{rule.id}", json=payload())
    assert response.status_code == 200
    assert response.json()["name"] == "新名"
    assert response.json()["conditions"] == [
        {"conditionId": "ma_rising", "params": {"period": 30}, "role": "premise"},
        {"conditionId": "custom", "params": {"signal_period": 5, "ratio": 0}, "role": "exit"},
    ]
    db.refresh(rule)
    assert rule.updated_at > datetime(2020, 1, 1)
    assert {c.condition_id: c.id for c in rule.conditions} == ids
    previous = rule.updated_at
    body = payload({"period": 40})
    body["name"] = "新名"
    assert client.put(f"/rules/{rule.id}", json=body).status_code == 200
    db.refresh(rule)
    assert rule.updated_at > previous


def test_null_removes_key(setup):
    client, _, rule = setup
    response = client.put(f"/rules/{rule.id}", json=payload({"min_slope_pct": None}))
    assert response.status_code == 200
    assert response.json()["conditions"][0]["params"] == {}


@pytest.mark.parametrize("change", ["remove", "reverse", "replace", "add"])
def test_reject_condition_changes(setup, change):
    client, _, rule = setup
    body = payload()
    if change == "remove":
        body["conditions"].pop()
    elif change == "reverse":
        body["conditions"].reverse()
    elif change == "replace":
        body["conditions"][0]["conditionId"] = "other"
    else:
        body["conditions"].append(body["conditions"][0])
    response = client.put(f"/rules/{rule.id}", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == "條件組合不能在編輯時變更"


@pytest.mark.parametrize("key,value", [
    ("period", 1.5), ("period", "20"), ("period", True), ("period", None),
    ("period", 0), ("slope_lookback", 0), ("min_slope_pct", -0.01),
    ("min_slope_pct", "0.1"), ("min_slope_pct", False), ("unknown", 1),
])
def test_invalid_params_do_not_mutate_rule(setup, key, value):
    client, db, rule = setup
    response = client.put(f"/rules/{rule.id}", json=payload({key: value}))
    assert response.status_code == 422
    assert "ma_rising" in response.json()["detail"]
    assert key in response.json()["detail"]
    db.refresh(rule)
    assert rule.name == "原名"
    assert rule.updated_at == datetime(2020, 1, 1)


def test_later_invalid_condition_is_atomic(setup):
    client, db, rule = setup
    body = payload()
    body["conditions"][1]["params"] = {"signal_period": 0}
    assert client.put(f"/rules/{rule.id}", json=body).status_code == 422
    db.refresh(rule)
    assert next(c for c in rule.conditions if c.condition_id == "ma_rising").params["period"] == 20


def test_missing_rule(setup):
    assert setup[0].put("/rules/9999", json=payload()).status_code == 404


def test_conditions_include_schema_and_defaults(setup):
    data = {c["id"]: c for c in setup[0].get("/conditions").json()}
    assert data["ma_rising"]["paramSchema"]["min_slope_pct"] == "float"
    assert data["ma_rising"]["originalDefaults"] == {
        "period": 20, "slope_lookback": 5, "min_slope_pct": None,
    }
    assert data["custom"]["originalDefaults"] == {}
