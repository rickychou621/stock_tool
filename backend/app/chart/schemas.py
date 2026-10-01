"""線圖對外API的回應格式。"""

from datetime import date

from app.core.schemas import CamelModel


class PriceBarSchema(CamelModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
