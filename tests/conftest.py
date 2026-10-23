import pytest
from fastapi.testclient import TestClient

from notification_api.api import create_app
from notification_api.config import Settings
from notification_api.database import Base

KEY = "test-only-not-a-real-secret-1234567890"


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, api_key=KEY, database_url=f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def app(settings):
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def headers():
    return {"X-API-Key": KEY, "Idempotency-Key": "example-001"}
