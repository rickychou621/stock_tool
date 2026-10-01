"""候選池的粗篩邏輯：兩階段篩選的第一階段，用便宜、粗略的條件(均線多頭排列、爆量)
從全部有資料的股票裡挑出候選名單，跟規則評估(精篩，見rules/evaluation.py)是不同層級。

跟規則評估一樣，先做成手動觸發版本(refresh())，排程之後只是定時呼叫同一個function。"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.conditions.indicators import calculate_sma
from app.conditions.loader import load_condition_bars
from app.conditions.types import ConditionBar
from app.market_data.repository import MarketDataRepository
from app.screening.repository import ScreeningRepository

MIN_BARS_REQUIRED = 25
VOLUME_LOOKBACK = 20
VOLUME_MULTIPLIER = 2.0


@dataclass
class CandidateRefreshSummary:
    stocks_scanned: int
    added: int
    expired: int
    active_total: int


class CandidatePoolService:
    def __init__(self, db: Session) -> None:
        self._market_data_repository = MarketDataRepository(db)
        self._screening_repository = ScreeningRepository(db)

    def refresh(self, limit: int = 10) -> CandidateRefreshSummary:
        tickers = self._market_data_repository.list_chartable_tickers()

        qualifying: list[tuple[str, str]] = []
        for ticker in tickers:
            bars = load_condition_bars(self._market_data_repository, ticker)
            reason = self._evaluate(bars)
            if reason:
                qualifying.append((ticker, reason))
        qualifying = qualifying[:limit]
        qualifying_tickers = {ticker for ticker, _ in qualifying}

        active = self._screening_repository.get_all_active()
        active_by_ticker = {candidate.ticker: candidate for candidate in active}

        expired = 0
        for candidate in active:
            if candidate.ticker not in qualifying_tickers:
                self._screening_repository.expire_candidate(candidate.id)
                expired += 1

        added = 0
        for ticker, reason in qualifying:
            existing = active_by_ticker.get(ticker)
            if existing is None:
                self._screening_repository.create_candidate(ticker, reason)
                added += 1
            elif existing.reason != reason:
                # 持續符合的候選股，也要把入選原因更新成這次算出來的最新理由，
                # 不然畫面上會一直顯示上一輪(甚至是很久以前)的舊理由文字。
                self._screening_repository.update_reason(existing.id, reason)

        return CandidateRefreshSummary(
            stocks_scanned=len(tickers),
            added=added,
            expired=expired,
            active_total=len(qualifying_tickers),
        )

    def _evaluate(self, bars: list[ConditionBar]) -> str | None:
        if len(bars) < MIN_BARS_REQUIRED:
            return None

        closes = [b.close for b in bars]
        volumes = [b.volume for b in bars]

        sma5 = calculate_sma(closes, 5)[-1]
        sma10 = calculate_sma(closes, 10)[-1]
        sma20 = calculate_sma(closes, 20)[-1]
        if sma5 is not None and sma10 is not None and sma20 is not None and sma5 > sma10 > sma20:
            return f"均線多頭排列(5MA={sma5:.1f} > 10MA={sma10:.1f} > 20MA={sma20:.1f})"

        recent_volumes = volumes[-(VOLUME_LOOKBACK + 1) : -1]
        avg_volume = sum(recent_volumes) / VOLUME_LOOKBACK if recent_volumes else 0
        latest_volume = volumes[-1]
        if avg_volume > 0 and latest_volume > avg_volume * VOLUME_MULTIPLIER:
            ratio = latest_volume / avg_volume
            return f"成交量較均量放大{ratio:.1f}倍"

        return None
