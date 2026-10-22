from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, MetaData, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.core.dependencies import get_db
from app.main import app
from app.market_data.models import Stock, StockPriceDaily


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    for table in metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, BigInteger):
                column.type = Integer()
    metadata.create_all(engine)
    with Session(engine) as db:
        for ticker, name, active, chartable in [
            ("0050", "元大台灣50", True, True),
            ("0060", "測試1303基金", True, True),
            ("1301", "台塑", True, True),
            ("1303", "南亞", True, True),
            ("13030", "測試延伸代號", True, True),
            ("1304", "測試無行情", True, False),
            ("1305", "測試停用", False, True),
            ("2408", "南亞科", True, True),
        ]:
            db.add(Stock(ticker=ticker, name=name, market="上市", is_active=active))
            if chartable:
                db.add(
                    StockPriceDaily(
                        ticker=ticker,
                        trade_date=date(2026, 10, 21),
                        open=100,
                        high=100,
                        low=100,
                        close=100,
                        volume=1000,
                    )
                )
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            with TestClient(app) as test_client:
                yield test_client
        finally:
            app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.mark.parametrize(
    "q, expected",
    [
        ("13", ["0060", "1301", "1303", "13030"]),
        ("亞", ["1303", "2408"]),
        ("1303", ["1303", "0060", "13030"]),
        ("  南亞  ", ["1303", "2408"]),
        ("不存在", []),
        ("%", []),
        ("_", []),
    ],
)
def test_search_matches_and_order(client, q, expected):
    response = client.get("/stocks", params={"q": q})
    assert response.status_code == 200
    assert [stock["ticker"] for stock in response.json()] == expected


def test_blank_search_matches_default_list(client):
    default = client.get("/stocks")
    blank = client.get("/stocks", params={"q": "   "})
    assert default.status_code == blank.status_code == 200
    assert blank.json() == default.json()


def test_search_filters_chartable_and_active_stocks(client):
    response = client.get("/stocks", params={"q": "1304"})
    assert response.status_code == 200
    assert response.json() == []
    all_stocks = client.get("/stocks", params={"q": "130", "chartable_only": False})
    assert all_stocks.status_code == 200
    assert [stock["ticker"] for stock in all_stocks.json()] == [
        "0060",
        "1301",
        "1303",
        "13030",
        "1304",
    ]


def test_search_applies_limit_after_exact_match_priority(client):
    response = client.get("/stocks", params={"q": "1303", "limit": 1})
    assert response.status_code == 200
    assert [stock["ticker"] for stock in response.json()] == ["1303"]


def test_search_rejects_query_over_twenty_characters(client):
    assert client.get("/stocks", params={"q": "a" * 21}).status_code == 422
