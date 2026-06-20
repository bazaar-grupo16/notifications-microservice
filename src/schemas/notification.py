"""Pydantic schemas for notification endpoints."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class NotificationStatus(StrEnum):
    """Allowed persisted notification states."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationType(StrEnum):
    """Business notification types supported by the service."""

    ORDER_STATUS_CHANGED = "order_status_changed"
    ORDER_ITEM_STATUS_CHANGED = "order_item_status_changed"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"


class NotificationCreate(BaseModel):
    """Request body for creating an internal notification."""

    idempotency_key: str = Field(min_length=1, max_length=255)
    notification_type: NotificationType = Field(alias="type")
    recipient_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class OrderStatusChangedNotificationCreate(BaseModel):
    """Request body for an order status change notification."""

    order_id: str = Field(min_length=1, max_length=128)
    buyer_id: str = Field(min_length=1, max_length=128)
    new_status: str = Field(min_length=1, max_length=64)
    order_name: str | None = Field(default=None, max_length=200)
    tracking_code: str | None = Field(default=None, max_length=100)


class OrderItemStatusChangedNotificationCreate(BaseModel):
    """Request body for an order item status change notification."""

    order_id: str = Field(min_length=1, max_length=128)
    item: str = Field(min_length=1, max_length=200)
    buyer_id: str = Field(min_length=1, max_length=128)
    new_status: str = Field(min_length=1, max_length=64)
    tracking_code: str | None = Field(default=None, max_length=100)


class LowStockNotificationCreate(BaseModel):
    """Request body for a low stock seller notification."""

    seller_id: str = Field(min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=128)
    product_name: str = Field(min_length=1, max_length=200)
    current_stock: int = Field(ge=0)
    threshold: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_low_stock_threshold(self) -> "LowStockNotificationCreate":
        """Ensure the event represents a low-stock condition."""
        if self.current_stock >= self.threshold:
            raise ValueError("current_stock must be lower than threshold")
        return self


class OutOfStockNotificationCreate(BaseModel):
    """Request body for an out-of-stock seller notification."""

    seller_id: str = Field(min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=128)
    product_name: str = Field(min_length=1, max_length=200)
    current_stock: int = Field(ge=0, le=0)


class NotificationResponse(BaseModel):
    """Response body for a persisted notification."""

    id: int
    idempotency_key: str
    notification_type: str = Field(alias="type")
    recipient_id: str
    title: str
    body: str
    payload: dict[str, Any]
    correlation_id: str | None
    status: NotificationStatus
    attempts: int
    last_error: str | None
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    read_at: datetime | None

    @computed_field
    @property
    def is_read(self) -> bool:
        """Whether the notification was read by the recipient."""
        return self.read_at is not None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class NotificationListResponse(BaseModel):
    """Paginated notification list response."""

    data: list[NotificationResponse]
    total: int
    limit: int
    offset: int


class NotificationUnreadCountResponse(BaseModel):
    """Unread notifications count response."""

    unread_count: int


class NotificationsReadAllResponse(BaseModel):
    """Bulk read operation response."""

    updated_count: int


class PushTokenCreate(BaseModel):
    """Request body for registering an Expo push token."""

    expo_push_token: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=32)


class PushTokenResponse(BaseModel):
    """Response body for a registered push token."""

    id: int
    recipient_id: str
    expo_push_token: str
    platform: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PushTokenDeleteResponse(BaseModel):
    """Response body for push token deactivation."""

    disabled: bool
