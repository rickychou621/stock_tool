"""Evaluation dates use Taipei trading dates supplied by the caller."""

from collections.abc import Iterable
from datetime import date


def is_evaluation_day(day: date, frequency: str) -> bool:
    """The caller guarantees day is a trading day, including holiday exclusions."""
    return frequency == "daily" or (frequency == "weekly" and day.weekday() == 4)


def last_evaluation_day(
    day: date, trading_days: Iterable[date], frequency: str,
) -> date | None:
    return max(
        (d for d in trading_days if d <= day and is_evaluation_day(d, frequency)),
        default=None,
    )
