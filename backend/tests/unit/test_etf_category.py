import pytest

from app.core.config import Settings
from app.market_scan.universe import etf_category


@pytest.mark.parametrize(("ticker", "expected"), [
    ("00631L", "leveraged"), ("00632R", "inverse"), ("00679B", "bond"),
    ("00980D", "bond"), ("00635U", "futures"), ("0050", "equity"),
    ("00980A", "equity"), ("00980K", "equity"), ("00980T", "equity"),
])
def test_etf_category_by_suffix(ticker, expected):
    assert etf_category(ticker, "etf") == expected


def test_stock_has_no_etf_category():
    assert etf_category("2330", "stock") is None


@pytest.mark.parametrize(("raw", "expected"), [
    (" leveraged, inverse, ,bond, ", {"leveraged", "inverse", "bond"}),
    ("", set()),
])
def test_excluded_categories_setting(raw, expected):
    assert Settings(screening_excluded_etf_categories=raw).excluded_etf_categories == expected
