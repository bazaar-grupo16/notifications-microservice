"""Lightweight worker for processing pending notifications."""

import logging
from datetime import timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from src.core.utils import utc_now
from src.models.notification import Notification
from src.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)


def _notification_log_context(notification: Notification) -> dict[str, object]:
    """Return common structured fields for notification logs."""
    return {
        "correlation_id": notification.correlation_id,
        "notification_id": notification.id,
        "notification_type": notification.notification_type,
        "recipient_id": notification.recipient_id,
        "status": notification.status,
        "attempts": notification.attempts,
    }


class NotificationSender(Protocol):
    """Sender interface used by the worker."""

    def send(self, notification: Notification) -> None:
        """Send a notification."""


class SimulatedNotificationSender:
    """Development sender used until push integration is added."""

    def send(self, notification: Notification) -> None:
        """Simulate notification delivery."""
        logger.info(
            "Simulated notification delivery",
            extra=_notification_log_context(notification),
        )


def process_pending_notifications(
    db: Session,
    *,
    limit: int = 10,
    max_attempts: int = 3,
    retry_delay_seconds: float = 30.0,
    sender: NotificationSender | None = None,
) -> int:
    """Process pending notifications and return how many were handled."""
    repository = NotificationRepository(db)
    notification_sender = sender or SimulatedNotificationSender()
    notifications = repository.list_pending(limit=limit, ready_at=utc_now())

    processed = 0
    for notification in notifications:
        notification.attempts += 1
        notification.last_error = None
        notification.next_retry_at = None

        try:
            notification_sender.send(notification)
        except Exception as exc:
            notification.last_error = str(exc)
            if notification.attempts >= max_attempts:
                notification.status = "failed"
            else:
                notification.status = "pending"
                notification.next_retry_at = utc_now() + timedelta(
                    seconds=retry_delay_seconds
                )
            logger.exception(
                "Notification processing failed",
                extra=_notification_log_context(notification),
            )
        else:
            notification.status = "sent"
            notification.sent_at = utc_now()
            logger.info(
                "Notification processing succeeded",
                extra=_notification_log_context(notification),
            )

        repository.save(notification)
        processed += 1

    return processed
