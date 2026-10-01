from datetime import date

import httpx
import pytest
import respx

from app.data_source.finmind_client import FINMIND_BASE_URL, FinMindClient


@respx.mock
def test_get_daily_price_parses_response() -> None:
    respx.get(FINMIND_BASE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "msg": "success",
                "status": 200,
                "data": [
                    {
                        "date": "2026-09-01",
                        "stock_id": "2330",
                        "Trading_Volume": 31855287,
                        "open": 2395.0,
                        "max": 2440.0,
                        "min": 2390.0,
                        "close": 2440.0,
                    }
                ],
            },
        )
    )

    bars = FinMindClient().get_daily_price("2330", days=10)

    assert bars == [
        {
            "trade_date": date(2026, 9, 1),
            "open": 2395.0,
            "high": 2440.0,
            "low": 2390.0,
            "close": 2440.0,
            "volume": 31855287,
        }
    ]


@respx.mock
def test_get_daily_price_raises_on_error_status() -> None:
    respx.get(FINMIND_BASE_URL).mock(
        return_value=httpx.Response(
            400, json={"msg": "Your level is free.", "status": 400}
        )
    )

    with pytest.raises(RuntimeError, match="FinMind回應錯誤"):
        FinMindClient().get_daily_price("2330")
