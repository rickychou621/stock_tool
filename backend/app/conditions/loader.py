"""把DB存的日K轉成條件庫共用的ConditionBar格式，RuleEvaluationService跟
CandidatePoolService都靠這個function拿資料，只寫一份轉換邏輯。"""

from app.conditions.types import ConditionBar
from app.market_data.repository import MarketDataRepository


def load_condition_bars(repository: MarketDataRepository, ticker: str) -> list[ConditionBar]:
    db_bars = repository.get_all_bars(ticker)
    return [
        ConditionBar(
            trade_date=bar.trade_date,
            open=float(bar.adj_open if bar.adj_open is not None else bar.open),
            high=float(bar.adj_high if bar.adj_high is not None else bar.high),
            low=float(bar.adj_low if bar.adj_low is not None else bar.low),
            close=float(bar.adj_close if bar.adj_close is not None else bar.close),
            volume=bar.volume,
        )
        for bar in db_bars
    ]
