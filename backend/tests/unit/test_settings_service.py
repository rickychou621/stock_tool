from app.core.config import Settings
from app.settings.service import SettingsService


def _make_settings(**overrides: object) -> Settings:
    return Settings(db_password="test", **overrides)  # type: ignore[arg-type]


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
