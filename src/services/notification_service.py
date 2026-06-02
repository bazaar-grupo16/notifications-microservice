"""Business rules for notification creation."""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.observability import get_observability_correlation_id
from src.models.notification import Notification
from src.repositories.notification_repository import NotificationRepository
from src.schemas.notification import (
    LowStockNotificationCreate,
    NotificationCreate,
    NotificationType,
    OrderStatusChangedNotificationCreate,
    OutOfStockNotificationCreate,
)


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

    def create_order_status_changed_notification(
        self,
        data: OrderStatusChangedNotificationCreate,
    ) -> NotificationCreationResult:
        """Create a notification for an order status change."""
        payload = {
            "order_id": data.order_id,
            "new_status": data.new_status,
            "deep_link": f"bazaar://orders/{data.order_id}",
        }
        if data.tracking_code is not None:
            payload["tracking_code"] = data.tracking_code

        return self.create_notification(
            NotificationCreate(
                idempotency_key=f"order:{data.order_id}:status:{data.new_status}",
                type=NotificationType.ORDER_STATUS_CHANGED,
                recipient_id=data.buyer_id,
                title="Estado de orden actualizado",
                body=f"Tu orden {data.order_id} cambió a {data.new_status}.",
                payload=payload,
            )
        )

    def create_low_stock_notification(
        self,
        data: LowStockNotificationCreate,
    ) -> NotificationCreationResult:
        """Create a notification for a product below its stock threshold."""
        return self.create_notification(
            NotificationCreate(
                idempotency_key=(
                    f"low_stock:{data.seller_id}:{data.product_id}:{data.threshold}"
                ),
                type=NotificationType.LOW_STOCK,
                recipient_id=data.seller_id,
                title="Stock bajo",
                body=(
                    f"El producto {data.product_name} tiene "
                    f"{data.current_stock} unidades disponibles."
                ),
                payload={
                    "seller_id": data.seller_id,
                    "product_id": data.product_id,
                    "product_name": data.product_name,
                    "current_stock": data.current_stock,
                    "threshold": data.threshold,
                    "deep_link": f"bazaar://seller/products/{data.product_id}",
                },
            )
        )

    def create_out_of_stock_notification(
        self,
        data: OutOfStockNotificationCreate,
    ) -> NotificationCreationResult:
        """Create a notification for a product without stock."""
        return self.create_notification(
            NotificationCreate(
                idempotency_key=f"out_of_stock:{data.seller_id}:{data.product_id}",
                type=NotificationType.OUT_OF_STOCK,
                recipient_id=data.seller_id,
                title="Producto sin stock",
                body=f"El producto {data.product_name} quedó sin stock.",
                payload={
                    "seller_id": data.seller_id,
                    "product_id": data.product_id,
                    "product_name": data.product_name,
                    "current_stock": data.current_stock,
                    "deep_link": f"bazaar://seller/products/{data.product_id}",
                },
            )
        )
