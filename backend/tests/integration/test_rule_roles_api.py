import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_db
from app.rules.models import WatchRule, WatchRuleCondition
from app.rules.router import router


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    WatchRule.__table__.create(engine)
    WatchRuleCondition.__table__.create(engine)
    app = FastAPI()
    app.include_router(router)
    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client
    engine.dispose()


def test_create_roles_and_read_back(client):
    conditions = [
        dict(conditionId="volume_spike", params={}, role=role)
        for role in ("premise", "entry", "exit")
    ]
    response = client.post("/rules", json=dict(
        name="roles", logicOperator="OR", conditions=conditions,
    ))
    assert response.status_code == 201
    assert response.json()["conditions"] == conditions
    assert client.get("/rules").json()[0]["conditions"] == conditions


def test_create_legacy_default(client):
    response = client.post("/rules", json=dict(
        name="legacy", logicOperator="AND",
        conditions=[dict(conditionId="volume_spike", params={})],
    ))
    assert response.status_code == 201
    assert response.json()["conditions"][0]["role"] == "premise"


@pytest.mark.parametrize("roles", [[], ["entry"], ["exit"], ["entry", "exit"], ["invalid"]])
def test_create_without_premise_or_invalid_role_returns_422(client, roles):
    response = client.post("/rules", json=dict(
        name="invalid", logicOperator="AND",
        conditions=[dict(conditionId="volume_spike", params={}, role=r) for r in roles],
    ))
    assert response.status_code == 422
    assert client.get("/rules").json() == []
