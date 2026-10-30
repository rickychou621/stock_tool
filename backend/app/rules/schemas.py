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
    evaluation_frequency: Literal["daily", "weekly"] = "daily"
    is_enabled: bool
    conditions: list[WatchRuleConditionSchema]


class WatchRuleCreateSchema(CamelModel):
    name: str
    logic_operator: str
    evaluation_frequency: Literal["daily", "weekly"] = "daily"
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


class RuleStateSchema(CamelModel):
    state: Literal["ENTRY", "HOLD", "NEAR_EXIT", "EXIT", "NONE", "NO_DATA", "STALE"]
    reason: str
    trigger_price: float | None
    close: float | None
    distance_pct: float | None
    ma_distance_pct: float | None = None
    ma_slope_pct: float | None = None


class RuleEvaluationSchema(CamelModel):
    evaluation_frequency: str = "daily"
    state: RuleStateSchema | None = None
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
    protective_stop: dict | None = None


class WatchRuleConditionUpdateSchema(CamelModel):
    condition_id: str
    params: dict


class WatchRuleUpdateSchema(CamelModel):
    name: str
    conditions: list[WatchRuleConditionUpdateSchema]
