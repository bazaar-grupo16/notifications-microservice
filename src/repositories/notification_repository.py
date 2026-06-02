"""Database access for notifications."""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.models.notification import Notification


class NotificationRepository:
    """Repository for notification persistence operations."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_idempotency_key(self, idempotency_key: str) -> Notification | None:
        """Return a notification matching the idempotency key, if it exists."""
        stmt = select(Notification).where(
            Notification.idempotency_key == idempotency_key
        )
        return self._db.execute(stmt).scalar_one_or_none()

    def create(self, notification: Notification) -> Notification:
        """Persist a new notification."""
        self._db.add(notification)
        self._db.commit()
        self._db.refresh(notification)
        return notification

    def list_pending(self, limit: int, *, ready_at: datetime) -> list[Notification]:
        """Return pending notifications ready to be processed."""
        stmt = (
            select(Notification)
            .where(Notification.status == "pending")
            .where(
                or_(
                    Notification.next_retry_at.is_(None),
                    Notification.next_retry_at <= ready_at,
                )
            )
            .order_by(Notification.created_at.asc(), Notification.id.asc())
            .limit(limit)
        )
        return list(self._db.execute(stmt).scalars().all())

    def save(self, notification: Notification) -> Notification:
        """Persist changes to an existing notification."""
        self._db.add(notification)
        self._db.commit()
        self._db.refresh(notification)
        return notification
