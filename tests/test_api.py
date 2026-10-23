from concurrent.futures import ThreadPoolExecutor

from notification_api.database import Notification

PAYLOAD = {"recipient": "demo", "text": "Inventory report ready"}


def test_authentication_and_health(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 401
    assert client.post("/v1/notifications", json=PAYLOAD).status_code == 401


def test_enqueue_replay_and_conflict(client, headers):
    original = client.post("/v1/notifications", json=PAYLOAD, headers=headers)
    assert original.status_code == 202
    replay = client.post("/v1/notifications", json=PAYLOAD, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["id"] == original.json()["id"]
    changed = {**PAYLOAD, "text": "A different message"}
    assert client.post("/v1/notifications", json=changed, headers=headers).status_code == 409


def test_concurrent_idempotency(client, headers, app):
    def post(_):
        return client.post("/v1/notifications", json=PAYLOAD, headers=headers)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(post, range(8)))
    assert {r.status_code for r in responses} <= {200, 202}
    assert len({r.json()["id"] for r in responses}) == 1
    with app.state.sessions() as session:
        assert session.query(Notification).count() == 1


def test_status_hides_message_and_key(client, headers):
    item = client.post("/v1/notifications", json=PAYLOAD, headers=headers).json()
    status = client.get(f"/v1/notifications/{item['id']}", headers=headers)
    assert status.status_code == 200
    assert status.json()["status"] == "pending"
    assert "text" not in status.json()
    assert "idempotency_key" not in status.json()


def test_validation(client, headers):
    for invalid in [
        {"recipient": "unknown", "text": "Hello"},
        {"recipient": "demo", "text": " "},
        {"recipient": "demo", "text": "x" * 4097},
        {**PAYLOAD, "chat_id": "123"},
    ]:
        assert client.post("/v1/notifications", json=invalid, headers=headers).status_code == 422
    assert (
        client.post(
            "/v1/notifications", json=PAYLOAD, headers={"X-API-Key": headers["X-API-Key"]}
        ).status_code
        == 422
    )


def test_missing_notification(client, headers):
    assert (
        client.get(
            "/v1/notifications/00000000-0000-0000-0000-000000000000", headers=headers
        ).status_code
        == 404
    )


def test_ready(client, headers):
    assert client.get("/health/ready", headers=headers).json()["delivery_mode"] == "mock"
