"""Pydantic schemas for notification endpoints."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NotificationStatus(StrEnum):
    """Allowed persisted notification states."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationCreate(BaseModel):
    """Request body for creating an internal notification."""

    idempotency_key: str = Field(min_length=1, max_length=255)
    notification_type: str = Field(alias="type", min_length=1, max_length=64)
    recipient_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


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
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
