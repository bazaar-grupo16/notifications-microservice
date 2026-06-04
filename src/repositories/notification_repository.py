"""Database access for notifications."""

from datetime import datetime

from sqlalchemy import func, or_, select, update
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

    def get_by_id_for_recipient(
        self,
        notification_id: int,
        recipient_id: str,
    ) -> Notification | None:
        """Return a notification owned by the recipient, if it exists."""
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_id == recipient_id,
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

    def list_by_recipient(
        self,
        recipient_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[Notification]:
        """Return notifications for a recipient ordered by newest first."""
        stmt = (
            select(Notification)
            .where(Notification.recipient_id == recipient_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._db.execute(stmt).scalars().all())

    def count_by_recipient(self, recipient_id: str) -> int:
        """Return total notifications for a recipient."""
        stmt = select(func.count()).select_from(Notification).where(
            Notification.recipient_id == recipient_id
        )
        return self._db.execute(stmt).scalar_one()

    def count_unread_by_recipient(self, recipient_id: str) -> int:
        """Return unread notifications count for a recipient."""
        stmt = select(func.count()).select_from(Notification).where(
            Notification.recipient_id == recipient_id,
            Notification.read_at.is_(None),
        )
        return self._db.execute(stmt).scalar_one()

    def mark_all_read_for_recipient(self, recipient_id: str, read_at: datetime) -> int:
        """Mark all unread notifications for a recipient as read."""
        stmt = (
            update(Notification)
            .where(
                Notification.recipient_id == recipient_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=read_at, updated_at=read_at)
        )
        result = self._db.execute(stmt)
        self._db.commit()
        return result.rowcount or 0

    def save(self, notification: Notification) -> Notification:
        """Persist changes to an existing notification."""
        self._db.add(notification)
        self._db.commit()
        self._db.refresh(notification)
        return notification
