from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = "sqlite:///./notifications.db"
    api_key: SecretStr = Field(min_length=32)
    delivery_mode: str = "mock"
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_destinations: dict[str, str] = {"demo": "0"}
    max_attempts: int = Field(default=4, ge=1, le=10)
    retry_base_seconds: int = Field(default=5, ge=1, le=3600)
    poll_seconds: float = Field(default=1, ge=0.1, le=60)

    @model_validator(mode="after")
    def validate_delivery(self):
        if self.delivery_mode not in {"mock", "telegram"}:
            raise ValueError("DELIVERY_MODE must be mock or telegram")
        if self.delivery_mode == "telegram" and not self.telegram_bot_token.get_secret_value():
            raise ValueError("TELEGRAM_BOT_TOKEN is required in telegram mode")
        if not self.telegram_destinations:
            raise ValueError("At least one named destination is required")
        return self
