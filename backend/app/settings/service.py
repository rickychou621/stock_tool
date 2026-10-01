from app.core.config import Settings
from app.data_source.notifier import TelegramNotifier


class SettingsService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_settings_summary(self) -> dict:
        return {
            "screening_interval_minutes": self._settings.screening_interval_minutes,
            "candidate_pool_limit": self._settings.candidate_pool_limit,
            "telegram_configured": bool(
                self._settings.telegram_bot_token and self._settings.telegram_chat_id
            ),
        }

    def send_test_telegram_message(self) -> tuple[bool, str]:
        notifier = TelegramNotifier(self._settings)
        try:
            notifier.send_alert("股票告警系統：這是一則測試訊息，收到代表Telegram串接成功。")
        except Exception as exc:  # noqa: BLE001 - 想把任何失敗原因都回報給前端顯示
            return False, str(exc)
        return True, "測試訊息已送出，請確認Telegram是否收到。"
