import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.settings.service import SettingsService


def _make_settings(**overrides: object) -> Settings:
    # Never inherit real notification credentials from the developer environment.
    values = dict(db_password="test", telegram_bot_token="", telegram_chat_id="")
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_get_settings_summary_reports_telegram_not_configured() -> None:
    service = SettingsService(_make_settings())

    summary = service.get_settings_summary()

    assert summary["telegram_configured"] is False
    assert summary["screening_interval_minutes"] == 5
    assert summary["candidate_pool_limit"] == 10


def test_get_settings_summary_reports_telegram_configured() -> None:
    service = SettingsService(
        _make_settings(telegram_bot_token="dummy-token", telegram_chat_id="123")
    )

    summary = service.get_settings_summary()

    assert summary["telegram_configured"] is True


def test_send_test_telegram_message_fails_gracefully_without_config() -> None:
    service = SettingsService(_make_settings())

    success, message = service.send_test_telegram_message()

    assert success is False
    assert "尚未設定" in message


@pytest.mark.parametrize("value", [-1, float("inf"), float("-inf"), float("nan")])
def test_market_scan_notify_min_turnover_rejects_invalid_values(value):
    with pytest.raises(ValidationError):
        _make_settings(market_scan_notify_min_turnover=value)


def test_market_scan_notify_min_turnover_default_and_environment(monkeypatch):
    monkeypatch.delenv("MARKET_SCAN_NOTIFY_MIN_TURNOVER", raising=False)
    assert Settings(_env_file=None).market_scan_notify_min_turnover == 10_000_000
    monkeypatch.setenv("MARKET_SCAN_NOTIFY_MIN_TURNOVER", "50000000")
    assert Settings(_env_file=None).market_scan_notify_min_turnover == 50_000_000
    monkeypatch.setenv("MARKET_SCAN_NOTIFY_MIN_TURNOVER", "0")
    assert Settings(_env_file=None).market_scan_notify_min_turnover == 0
