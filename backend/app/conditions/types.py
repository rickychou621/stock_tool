from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ConditionBar:
    """條件評估的共同輸入格式：一根K棒。日K/月K都用這個型別，
    月K條件自己在evaluate()裡呼叫indicators.resample_to_monthly()做轉換。"""

    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
