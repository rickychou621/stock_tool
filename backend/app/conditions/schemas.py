"""條件庫清單對外API的回應格式。"""

from app.core.schemas import CamelModel


class ConditionCatalogSchema(CamelModel):
    id: str
    name: str
    description: str
    required_timeframe: str
    update_frequency: str
