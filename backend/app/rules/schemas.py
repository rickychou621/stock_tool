"""規則組合對外API的請求/回應格式。"""

from datetime import date
from typing import Literal

from pydantic import model_validator

from app.core.schemas import CamelModel


class WatchRuleConditionSchema(CamelModel):
    condition_id: str
    params: dict
    role: Literal["premise", "entry", "exit"] = "premise"


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

    @model_validator(mode="after")
    def require_premise(self):
        if not any(c.role == "premise" for c in self.conditions):
            raise ValueError("戰法缺少前提條件")
        return self


class ConditionEvaluationSchema(CamelModel):
    role: Literal["premise", "entry", "exit"] = "premise"
    condition_id: str
    is_met: bool
    reason: str
    data_sufficient: bool = True
    upper_band_status: Literal["touched", "breakout"] | None = None


class RuleEvaluationSchema(CamelModel):
    premise_met: bool
    entry_triggered: bool | None
    exit_triggered: bool | None
    rule_id: int
    ticker: str
    is_met: bool
    logic_operator: str
    status: str
    data_date: date | None
    condition_results: list[ConditionEvaluationSchema]
