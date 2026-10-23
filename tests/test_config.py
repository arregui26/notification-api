import pytest
from pydantic import ValidationError

from notification_api.config import Settings


def test_short_key_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_key="short")


def test_telegram_requires_token():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_key="x" * 32, delivery_mode="telegram", telegram_bot_token="")


def test_unknown_delivery_mode_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_key="x" * 32, delivery_mode="unknown")
