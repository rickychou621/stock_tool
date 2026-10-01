"""股票主檔對外API的回應格式。"""

from app.core.schemas import CamelModel


class StockSchema(CamelModel):
    ticker: str
    name: str
    sector: str = ""
