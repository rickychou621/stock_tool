from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """對外API的schema共同基底：Python端維持snake_case慣例，JSON回應/請求自動轉camelCase
    對接前端的命名慣例(FastAPI預設用alias做response序列化，populate_by_name讓輸入兩種命名都吃)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
