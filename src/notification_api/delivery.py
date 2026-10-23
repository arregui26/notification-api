import httpx

from notification_api.config import Settings
from notification_api.database import Notification


class DeliveryError(Exception):
    def __init__(self, code: str, retryable: bool, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


class TelegramSender:
    def __init__(self, settings: Settings, client: httpx.Client):
        self.settings = settings
        self.client = client

    def send(self, notification: Notification) -> str:
        if notification.delivery_mode != self.settings.delivery_mode:
            raise DeliveryError("delivery_mode_changed", False)
        if self.settings.delivery_mode == "mock":
            return f"mock-{notification.id}"
        chat_id = self.settings.telegram_destinations.get(notification.recipient)
        if chat_id is None:
            raise DeliveryError("destination_removed", False)
        token = self.settings.telegram_bot_token.get_secret_value()
        try:
            response = self.client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": notification.text},
            )
        except httpx.RequestError:
            # Never log exception text: Telegram URLs contain the bot token.
            raise DeliveryError("network_error", True) from None
        if response.status_code == 429:
            try:
                seconds = int(response.json().get("parameters", {}).get("retry_after", 30))
            except (ValueError, TypeError, AttributeError):
                seconds = 30
            raise DeliveryError("provider_rate_limited", True, max(1, min(seconds, 3600)))
        if response.status_code >= 500:
            raise DeliveryError("provider_unavailable", True)
        if response.status_code != 200:
            raise DeliveryError("provider_rejected", False)
        try:
            data = response.json()
            if data.get("ok") is not True:
                raise ValueError
            return str(data["result"]["message_id"])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise DeliveryError("invalid_provider_response", True) from None
