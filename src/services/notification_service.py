"""Business rules for notification creation."""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.observability import get_observability_correlation_id
from src.models.notification import Notification
from src.repositories.notification_repository import NotificationRepository
from src.schemas.notification import NotificationCreate


@dataclass(frozen=True)
class NotificationCreationResult:
    """Result of an idempotent notification creation attempt."""

    notification: Notification
    created: bool


class NotificationService:
    """Application service for persisted notifications."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repository = NotificationRepository(db)

    def create_notification(
        self,
        data: NotificationCreate,
    ) -> NotificationCreationResult:
        """Create a pending notification, or return the existing one."""
        existing = self._repository.get_by_idempotency_key(data.idempotency_key)
        if existing is not None:
            return NotificationCreationResult(notification=existing, created=False)

        notification = Notification(
            idempotency_key=data.idempotency_key,
            notification_type=data.notification_type,
            recipient_id=data.recipient_id,
            title=data.title,
            body=data.body,
            payload=data.payload,
            correlation_id=get_observability_correlation_id(),
            status="pending",
        )

        try:
            created = self._repository.create(notification)
        except IntegrityError:
            self._db.rollback()
            existing = self._repository.get_by_idempotency_key(data.idempotency_key)
            if existing is None:
                raise
            return NotificationCreationResult(notification=existing, created=False)

        return NotificationCreationResult(notification=created, created=True)
