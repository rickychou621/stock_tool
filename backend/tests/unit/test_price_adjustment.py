from datetime import date

from app.market_data.price_adjustment import (
    DividendEvent,
    PriceBar,
    apply_adjustment,
    calculate_adjustment_factor,
)


def test_calculate_adjustment_factor_matches_worked_example() -> None:
    # 股價100元、現金股利2元、股票股利3元(無償配股率0.3)
    # 除權息參考價 = (100-2)/1.3 = 75.4元
    event = DividendEvent(
        ex_dividend_date=date(2026, 1, 2), cash_dividend=2.0, stock_dividend_ratio=0.3
    )

    factor = calculate_adjustment_factor(prev_close=100.0, event=event)

    assert round(100.0 * factor, 2) == 75.38


def test_apply_adjustment_smooths_pure_cash_dividend_gap() -> None:
    bars = [
        PriceBar(date(2026, 1, 1), open=100.0, high=101.0, low=99.0, close=100.0),
        PriceBar(date(2026, 1, 2), open=98.0, high=98.5, low=97.0, close=98.0),  # 除息當天
        PriceBar(date(2026, 1, 3), open=98.5, high=99.0, low=98.0, close=99.0),
    ]
    events = [DividendEvent(ex_dividend_date=date(2026, 1, 2), cash_dividend=2.0)]

    adjusted = apply_adjustment(bars, events)

    # 除息日之後(含當天)不受影響
    assert adjusted[date(2026, 1, 3)]["close"] == 99.0
    assert adjusted[date(2026, 1, 2)]["close"] == 98.0
    # 除息日之前要乘上調整係數((100-2)/100=0.98)
    assert round(adjusted[date(2026, 1, 1)]["close"], 2) == 98.0


def test_apply_adjustment_with_no_events_returns_raw_prices() -> None:
    bars = [PriceBar(date(2026, 1, 1), open=10.0, high=11.0, low=9.0, close=10.5)]

    adjusted = apply_adjustment(bars, events=[])

    assert adjusted[date(2026, 1, 1)]["close"] == 10.5
