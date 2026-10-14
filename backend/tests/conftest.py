"""HTTP tests must not start background jobs against the development database."""

import pytest


@pytest.fixture(autouse=True)
def disable_background_scheduler(monkeypatch):
    monkeypatch.setattr("app.main.start_scheduler", lambda: None)
    monkeypatch.setattr("app.main.stop_scheduler", lambda: None)

    monkeypatch.setattr("app.main.backtest_manager.recover", lambda: None)
    monkeypatch.setattr("app.main.backtest_manager.close", lambda: None)

    monkeypatch.setattr("app.main.market_scan_manager.recover", lambda: None)
    monkeypatch.setattr("app.main.market_scan_manager.close", lambda: None)
