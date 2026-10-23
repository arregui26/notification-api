"""Real locking and uniqueness tests; only use a disposable *_test database."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from notification_api.api import create_app
from notification_api.config import Settings
from notification_api.database import Notification
from notification_api.worker import process_one

pytestmark = pytest.mark.postgres
KEY = "test-only-not-a-real-secret-1234567890"


@pytest.fixture
def pg():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for real PostgreSQL tests")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must point to a disposable database ending in _test")
    settings = Settings(_env_file=None, api_key=KEY, database_url=url)
    app = create_app(settings)
    with app.state.sessions.begin() as session:
        session.execute(delete(Notification))
    with TestClient(app) as client:
        yield app, client, settings


def test_postgres_concurrent_enqueue(pg):
    app, client, _ = pg

    def send(_):
        return client.post(
            "/v1/notifications",
            headers={"X-API-Key": KEY, "Idempotency-Key": "postgres-race"},
            json={"recipient": "demo", "text": "Concurrent test"},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send, range(16)))
    assert {r.status_code for r in responses} <= {200, 202}
    assert len({r.json()["id"] for r in responses}) == 1
    with app.state.sessions() as session:
        assert session.query(Notification).count() == 1


def test_worker_skips_locked_notification(pg):
    app, client, settings = pg
    client.post(
        "/v1/notifications",
        headers={"X-API-Key": KEY, "Idempotency-Key": "locking"},
        json={"recipient": "demo", "text": "Lock test"},
    )
    acquired = threading.Event()
    release = threading.Event()

    class SlowSender:
        def send(self, item):
            acquired.set()
            assert release.wait(5)
            return "mock-lock-test"

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(process_one, app.state.sessions, SlowSender(), settings)
        try:
            assert acquired.wait(5)
            assert process_one(app.state.sessions, SlowSender(), settings) is False
        finally:
            release.set()
        assert first.result(timeout=5) is True
    with app.state.sessions() as session:
        item = session.query(Notification).one()
        assert (item.status, item.attempts) == ("sent", 1)
