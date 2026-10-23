import logging
import signal
import threading
from datetime import timedelta

import httpx
from sqlalchemy import select

from notification_api.config import Settings
from notification_api.database import Notification, make_database, utcnow
from notification_api.delivery import DeliveryError, TelegramSender

logger = logging.getLogger(__name__)


def process_one(sessions, sender, settings: Settings) -> bool:
    """Hold a row lock through delivery; PostgreSQL workers skip other locked rows."""
    with sessions.begin() as session:
        item = session.scalar(
            select(Notification)
            .where(
                Notification.status.in_(["pending", "retry"]), Notification.available_at <= utcnow()
            )
            .order_by(Notification.available_at, Notification.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if item is None:
            return False
        item.attempts += 1
        try:
            item.provider_message_id = sender.send(item)
        except DeliveryError as error:
            item.last_error = error.code
            if error.retryable and item.attempts < settings.max_attempts:
                item.status = "retry"
                delay = error.retry_after or min(
                    settings.retry_base_seconds * 2 ** (item.attempts - 1), 3600
                )
                item.available_at = utcnow() + timedelta(seconds=delay)
            else:
                item.status = "failed"
        else:
            item.status = "sent"
            item.sent_at = utcnow()
            item.last_error = None
        logger.info("notification=%s status=%s attempt=%s", item.id, item.status, item.attempts)
        return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx request logging would expose the token embedded in Telegram's URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    engine, sessions = make_database(settings.database_url)
    if engine.dialect.name != "postgresql":
        raise SystemExit("The worker requires PostgreSQL for safe concurrent row locking")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            sender = TelegramSender(settings, client)
            while not stop.is_set():
                try:
                    processed = process_one(sessions, sender, settings)
                except Exception:
                    # No raw exception/URL/message content in operational logs.
                    logger.error("Worker cycle failed; database or configuration needs attention")
                    processed = False
                if not processed:
                    stop.wait(settings.poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
