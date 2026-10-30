"""Evaluation dates use Taipei trading dates supplied by the caller."""

from collections.abc import Iterable
from datetime import date


def weekly_evaluation_days(trading_days: Iterable[date]) -> set[date]:
    last_by_week: dict[tuple[int, int], date] = {}
    for day in trading_days:
        week = day.isocalendar()[:2]
        last_by_week[week] = max(day, last_by_week.get(week, day))
    latest_week = max(last_by_week, default=None)
    return {
        day for week, day in last_by_week.items()
        if day.weekday() == 4 or week != latest_week
    }


def is_evaluation_day(day: date, frequency: str, trading_days: Iterable[date]) -> bool:
    """The caller guarantees day is a trading day, including holiday exclusions."""
    return frequency == "daily" or (
        frequency == "weekly" and day in weekly_evaluation_days(trading_days)
    )


def last_evaluation_day(
    day: date, trading_days: Iterable[date], frequency: str,
) -> date | None:
    candidates = weekly_evaluation_days(trading_days) if frequency == "weekly" else trading_days
    if frequency not in ("daily", "weekly"):
        return None
    return max((d for d in candidates if d <= day), default=None)
