"""規則組合對外API的請求/回應格式。"""

from datetime import date

from app.core.schemas import CamelModel


class WatchRuleConditionSchema(CamelModel):
    condition_id: str
    params: dict


class WatchRuleSchema(CamelModel):
    id: int
    name: str
    logic_operator: str
    is_enabled: bool
    conditions: list[WatchRuleConditionSchema]


class WatchRuleCreateSchema(CamelModel):
    name: str
    logic_operator: str
    conditions: list[WatchRuleConditionSchema]


class ConditionEvaluationSchema(CamelModel):
    condition_id: str
    is_met: bool
    reason: str
    data_sufficient: bool = True


class RuleEvaluationSchema(CamelModel):
    rule_id: int
    ticker: str
    is_met: bool
    logic_operator: str
    status: str
    data_date: date | None
    condition_results: list[ConditionEvaluationSchema]
