"""Shared proportional costs. No minimum commission, slippage or day-trade tax relief."""

from dataclasses import asdict, dataclass
from math import isfinite


@dataclass(frozen=True)
class TradingCosts:
    fee_rate: float = 0.001425
    fee_discount: float = 1.0
    tax_rate_stock: float = 0.003
    tax_rate_etf: float = 0.001

    def __post_init__(self):
        if not all(isfinite(v) for v in asdict(self).values()):
            raise ValueError("交易成本必須為有限數字")
        if (
            not 0 < self.fee_discount <= 1
            or any(not 0 <= v < 1 for v in (self.fee_rate, self.tax_rate_stock, self.tax_rate_etf))
            or self.fee_rate * self.fee_discount + max(self.tax_rate_stock, self.tax_rate_etf) >= 1
        ):
            raise ValueError("交易成本比例無效")

    def snapshot(self):
        return dict(
            feeRate=self.fee_rate,
            feeDiscount=self.fee_discount,
            taxRateStock=self.tax_rate_stock,
            taxRateEtf=self.tax_rate_etf,
        )

    @classmethod
    def from_snapshot(cls, snapshot):
        return cls(
            snapshot["feeRate"],
            snapshot["feeDiscount"],
            snapshot["taxRateStock"],
            snapshot["taxRateEtf"],
        )

    def net_return(self, entry, exit, kind="stock"):
        if not all(isfinite(v) and v > 0 for v in (entry, exit)):
            raise ValueError("進出場價格必須為有限正數")
        fee = self.fee_rate * self.fee_discount
        tax = self.tax_rate_etf if kind == "etf" else self.tax_rate_stock
        return exit * (1 - fee - tax) / (entry * (1 + fee)) - 1

    @classmethod
    def from_settings(cls, settings):
        return cls(**{key: getattr(settings, "trade_" + key) for key in cls.__dataclass_fields__})
