"""Normalize source prices without deriving ratios from stored daily bars."""

from datetime import date
from decimal import Decimal

TYPES = {"分割": "split", "反分割": "reverse_split", "面額變更": "par_value_change"}


def price_event(ticker, day, kind, before, reference, source, start, end):
    before = Decimal(str(before).replace(",", ""))
    reference = Decimal(str(reference).replace(",", ""))
    if (
        not ticker
        or not start <= day <= end
        or not before.is_finite()
        or not reference.is_finite()
        or before <= 0
        or reference <= 0
    ):
        raise ValueError("價格事件日期或價格無效")
    return dict(
        ticker=ticker,
        event_date=day,
        event_type=kind,
        before_close=before,
        reference_price=reference,
        source=source,
    )


def parse_finmind(rows, start, end):
    return [
        price_event(
            str(r["stock_id"]).strip(),
            date.fromisoformat(r["date"]),
            TYPES[r["type"]],
            r["before_price"],
            r["after_price"],
            "finmind_split",
            start,
            end,
        )
        for r in rows
    ]
