import hashlib
import json
import secrets
from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from notification_api.config import Settings
from notification_api.database import Notification, make_database


class NotificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    text: str = Field(min_length=1, max_length=4096)


class NotificationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    recipient: str
    status: str
    attempts: int
    delivery_mode: str
    last_error: str | None
    provider_message_id: str | None
    created_at: datetime
    available_at: datetime
    sent_at: datetime | None


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine, sessions = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(
        title="Notification API",
        version="0.1.0",
        description="Durable notifications. Mock mode by default; Telegram via named destinations.",
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.sessions = sessions
    key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def authorize(key: Annotated[str | None, Depends(key_header)]):
        if key is None or not secrets.compare_digest(
            key.encode(), settings.api_key.get_secret_value().encode()
        ):
            raise HTTPException(status_code=401, detail="Invalid API key")

    def database() -> Generator[Session]:
        with sessions() as session:
            yield session

    auth = [Depends(authorize)]

    @app.get("/health/live", tags=["Health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", dependencies=auth, tags=["Health"])
    def ready(session: Annotated[Session, Depends(database)]):
        try:
            session.execute(text("SELECT 1 FROM notifications LIMIT 1"))
        except Exception:
            raise HTTPException(503, "Database or migrations unavailable") from None
        return {"status": "ready", "delivery_mode": settings.delivery_mode}

    @app.post(
        "/v1/notifications",
        status_code=202,
        response_model=NotificationOutput,
        dependencies=auth,
        tags=["Notifications"],
    )
    def enqueue(
        body: NotificationInput,
        response: Response,
        session: Annotated[Session, Depends(database)],
        idempotency_key: Annotated[
            str, Header(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")
        ],
    ):
        if body.recipient not in settings.telegram_destinations:
            raise HTTPException(422, "Unknown named destination")
        if not body.text.strip():
            raise HTTPException(422, "Message must not be blank")
        digest = hashlib.sha256(
            json.dumps(body.model_dump(), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

        def replay(existing):
            if existing.payload_hash != digest:
                raise HTTPException(409, "Idempotency key already used for another payload")
            response.status_code = 200
            return existing

        existing = session.scalar(
            select(Notification).where(Notification.idempotency_key == idempotency_key)
        )
        if existing:
            return replay(existing)
        item = Notification(
            **body.model_dump(),
            idempotency_key=idempotency_key,
            payload_hash=digest,
            delivery_mode=settings.delivery_mode,
        )
        session.add(item)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(Notification).where(Notification.idempotency_key == idempotency_key)
            )
            if existing is None:
                raise
            return replay(existing)
        return item

    @app.get(
        "/v1/notifications/{notification_id}",
        response_model=NotificationOutput,
        dependencies=auth,
        tags=["Notifications"],
    )
    def get_notification(notification_id: UUID, session: Annotated[Session, Depends(database)]):
        item = session.get(Notification, notification_id)
        if item is None:
            raise HTTPException(404, "Notification not found")
        return item

    return app
