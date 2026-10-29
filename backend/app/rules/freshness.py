"""Expected market data dates for daily and weekly evaluations."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.market_data.models import StockPriceDaily
from app.rules.frequency import last_evaluation_day


def latest_trading_days(db: Session) -> tuple[date | None, list[date]]:
    latest = db.scalar(select(func.max(StockPriceDaily.trade_date)))
    trading_days = list(db.scalars(
        select(StockPriceDaily.trade_date).distinct()
        .where(StockPriceDaily.trade_date >= latest - timedelta(days=21))
    )) if latest else []
    return latest, trading_days


def expected_data_date(
    latest: date | None, trading_days: list[date], frequency: str,
) -> date | None:
    return last_evaluation_day(latest, trading_days, frequency) if latest else None
