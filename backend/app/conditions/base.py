"""條件庫共同介面。每個技術判斷條件(EMA交叉、布林通道、KD/MACD、爆量等)都應繼承 Condition，
並用 registry.register_condition 註冊，讓規則組合(rules/)可以用條件id自由引用、組裝AND/OR。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

from app.conditions.types import ConditionBar


class UpdateFrequency(StrEnum):
    REALTIME = "realtime"
    DAILY = "daily"
    MONTHLY = "monthly"


@dataclass
class ConditionResult:
    is_met: bool
    reason: str
    data_sufficient: bool = True


class Condition(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    required_timeframe: ClassVar[str]
    update_frequency: ClassVar[UpdateFrequency]

    @abstractmethod
    def evaluate(self, bars: list[ConditionBar], params: dict[str, Any]) -> ConditionResult:
        """輸入依日期升冪排序的日K序列(還原股價)與該條件的參數，回傳是否成立及觸發原因。
        月K相關的條件自己內部做resample，呼叫端一律只需要準備日K。"""
        raise NotImplementedError
