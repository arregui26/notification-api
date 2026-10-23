from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from notification_api.database import Notification
from notification_api.delivery import DeliveryError, TelegramSender


def notification():
    return Notification(id=uuid4(), recipient="demo", text="Hello", delivery_mode="telegram")


def test_telegram_request_and_success(settings):
    settings.delivery_mode = "telegram"
    settings.telegram_bot_token = SecretStr("test-token")

    def respond(request):
        assert request.url.host == "api.telegram.org"
        assert b'"chat_id":"0"' in request.content
        assert b"parse_mode" not in request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert TelegramSender(settings, client).send(notification()) == "42"


@pytest.mark.parametrize(
    "status,body,code,retryable",
    [
        (429, {"parameters": {"retry_after": 12}}, "provider_rate_limited", True),
        (503, {}, "provider_unavailable", True),
        (403, {}, "provider_rejected", False),
        (200, {"ok": False}, "invalid_provider_response", True),
    ],
)
def test_provider_failures(settings, status, body, code, retryable):
    settings.delivery_mode = "telegram"
    settings.telegram_bot_token = SecretStr("never-expose-this-token")
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    ) as client:
        with pytest.raises(DeliveryError) as failure:
            TelegramSender(settings, client).send(notification())
    assert failure.value.code == code
    assert failure.value.retryable == retryable
    assert "never-expose" not in str(failure.value)
    if status == 429:
        assert failure.value.retry_after == 12


def test_network_exception_is_sanitized(settings):
    settings.delivery_mode = "telegram"
    settings.telegram_bot_token = SecretStr("never-expose-this-token")

    def fail(request):
        raise httpx.ConnectError(str(request.url))

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(DeliveryError, match="^network_error$"):
            TelegramSender(settings, client).send(notification())


def test_mock_mode_never_calls_provider(settings):
    def forbidden(_):
        raise AssertionError("Mock mode must not send requests")

    item = notification()
    item.delivery_mode = "mock"
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        assert TelegramSender(settings, client).send(item).startswith("mock-")
