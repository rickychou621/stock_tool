"""條件註冊機制：新增條件只需要寫一個Condition子類別並用@register_condition註冊，
不需要修改排程或規則評估的核心流程。"""

from app.conditions.base import Condition

_registry: dict[str, type[Condition]] = {}


def register_condition(condition_cls: type[Condition]) -> type[Condition]:
    _registry[condition_cls.id] = condition_cls
    return condition_cls


def get_condition(condition_id: str) -> type[Condition]:
    return _registry[condition_id]


def list_conditions() -> list[type[Condition]]:
    return list(_registry.values())
