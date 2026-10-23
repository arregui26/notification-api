from datetime import timedelta
from uuid import UUID

import pytest

from notification_api.database import Notification, utcnow
from notification_api.delivery import DeliveryError
from notification_api.worker import process_one


class Sender:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def send(self, item):
        self.calls += 1
        if self.error:
            raise self.error
        return "provider-42"


def enqueue(client, headers):
    return UUID(
        client.post(
            "/v1/notifications", headers=headers, json={"recipient": "demo", "text": "Hello"}
        ).json()["id"]
    )


def test_success_not_delivered_twice(client, headers, app, settings):
    item_id = enqueue(client, headers)
    sender = Sender()
    assert process_one(app.state.sessions, sender, settings)
    assert not process_one(app.state.sessions, sender, settings)
    assert sender.calls == 1
    with app.state.sessions() as session:
        item = session.get(Notification, item_id)
        assert item.status == "sent"
        assert item.attempts == 1
        assert item.sent_at is not None


def test_retry_backoff_and_exhaustion(client, headers, app, settings):
    item_id = enqueue(client, headers)
    settings.max_attempts = 2
    sender = Sender(DeliveryError("provider_unavailable", True))
    before = utcnow()
    assert process_one(app.state.sessions, sender, settings)
    assert not process_one(app.state.sessions, sender, settings)
    with app.state.sessions.begin() as session:
        item = session.get(Notification, item_id)
        assert item.status == "retry"
        assert item.available_at.replace(tzinfo=before.tzinfo) >= before
        item.available_at = utcnow() - timedelta(seconds=1)
    process_one(app.state.sessions, sender, settings)
    with app.state.sessions() as session:
        item = session.get(Notification, item_id)
        assert (item.status, item.attempts) == ("failed", 2)


def test_permanent_error_is_not_retried(client, headers, app, settings):
    item_id = enqueue(client, headers)
    process_one(app.state.sessions, Sender(DeliveryError("provider_rejected", False)), settings)
    with app.state.sessions() as session:
        assert session.get(Notification, item_id).status == "failed"


def test_unexpected_error_rolls_back(client, headers, app, settings):
    item_id = enqueue(client, headers)
    with pytest.raises(RuntimeError):
        process_one(app.state.sessions, Sender(RuntimeError("unexpected")), settings)
    with app.state.sessions() as session:
        item = session.get(Notification, item_id)
        assert (item.status, item.attempts) == ("pending", 0)
