from datetime import date, timedelta

from app.conditions.types import ConditionBar
from app.screening.candidate_service import CandidatePoolService


def _bar(day_offset: int, close: float, volume: int = 1000) -> ConditionBar:
    trade_date = date(2026, 1, 1) + timedelta(days=day_offset)
    return ConditionBar(
        trade_date=trade_date, open=close, high=close, low=close, close=close, volume=volume
    )


def _evaluate(bars: list[ConditionBar]) -> str | None:
    # _evaluate只用到純計算，不碰DB，直接建一個不連DB的instance來測試。
    service = CandidatePoolService.__new__(CandidatePoolService)
    return service._evaluate(bars)  # noqa: SLF001 - 特意測內部的純邏輯


def test_not_enough_bars_returns_none() -> None:
    bars = [_bar(i, 100.0) for i in range(10)]
    assert _evaluate(bars) is None


def test_ma_bullish_alignment_qualifies() -> None:
    # 持續上漲的收盤價，5MA會排在10MA、20MA之上。
    closes = [100.0 + i * 2 for i in range(30)]
    bars = [_bar(i, c) for i, c in enumerate(closes)]
    reason = _evaluate(bars)
    assert reason is not None
    assert "均線多頭排列" in reason


def test_volume_spike_qualifies_when_no_ma_alignment() -> None:
    # 收盤價持平(不會觸發均線排列)，但最後一天成交量暴增。
    bars = [_bar(i, 100.0, volume=1000) for i in range(30)]
    bars[-1] = _bar(29, 100.0, volume=5000)
    reason = _evaluate(bars)
    assert reason is not None
    assert "成交量" in reason


def test_flat_series_no_volume_spike_does_not_qualify() -> None:
    bars = [_bar(i, 100.0, volume=1000) for i in range(30)]
    assert _evaluate(bars) is None
