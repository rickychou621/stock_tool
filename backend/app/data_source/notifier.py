"""Telegram 推播封裝，使用官方 Bot API 的 sendMessage endpoint。"""

import httpx

from app.core.config import Settings


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._settings.telegram_bot_token}/{method}"

    def send_alert(self, message: str) -> None:
        if not self._settings.telegram_bot_token or not self._settings.telegram_chat_id:
            raise ValueError("Telegram 尚未設定 bot token 或 chat id")

        response = httpx.post(
            self._api_url("sendMessage"),
            json={"chat_id": self._settings.telegram_chat_id, "text": message},
            timeout=10,
        )
        response.raise_for_status()
