"""共用市場資料表：不屬於單一feature，screening/chart/conditions評估都會讀取這裡的資料。"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    market: Mapped[str] = mapped_column(String(10))
    sector: Mapped[str] = mapped_column(String(80), default="", server_default="")
    data_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockPriceDaily(Base):
    """日K(來源:FinMind TaiwanStockPrice，未還原的原始成交價)。
    adj_*欄位是自己用股利事件(見StockDividendEvent)反推的還原股價，
    圖表/技術指標一律應該用adj_*欄位，raw的open/high/low/close保留原始成交價當歷史紀錄。"""

    __tablename__ = "stock_price_daily"
    __table_args__ = (UniqueConstraint("ticker", "trade_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.ticker"), index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    open: Mapped[float] = mapped_column(Numeric(10, 2))
    high: Mapped[float] = mapped_column(Numeric(10, 2))
    low: Mapped[float] = mapped_column(Numeric(10, 2))
    close: Mapped[float] = mapped_column(Numeric(10, 2))
    volume: Mapped[int] = mapped_column(BigInteger)
    adj_open: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    adj_high: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    adj_low: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    adj_close: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockDividendEvent(Base):
    """股利/增資事件(來源:FinMind TaiwanStockDividend)，用來反推還原股價的調整係數。"""

    __tablename__ = "stock_dividend_events"
    __table_args__ = (UniqueConstraint("ticker", "ex_dividend_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.ticker"), index=True)
    ex_dividend_date: Mapped[date] = mapped_column(Date)
    cash_dividend: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    stock_dividend_ratio: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    cash_capital_increase_ratio: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    cash_capital_increase_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockPriceIntraday(Base):
    """盤中分K，供左側爆量城牆K等歷史比對使用。"""

    __tablename__ = "stock_price_intraday"
    __table_args__ = (UniqueConstraint("ticker", "timeframe", "bar_time"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.ticker"), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    bar_time: Mapped[datetime] = mapped_column(DateTime)
    open: Mapped[float] = mapped_column(Numeric(10, 2))
    high: Mapped[float] = mapped_column(Numeric(10, 2))
    low: Mapped[float] = mapped_column(Numeric(10, 2))
    close: Mapped[float] = mapped_column(Numeric(10, 2))
    volume: Mapped[int] = mapped_column(BigInteger)
