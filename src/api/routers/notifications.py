"""HTTP routes for internal notification events."""

from fastapi import APIRouter, Response, status

from src.core.dependencies import DbSession
from src.schemas.notification import (
    LowStockNotificationCreate,
    NotificationCreate,
    NotificationResponse,
    OrderStatusChangedNotificationCreate,
    OutOfStockNotificationCreate,
)
from src.services.notification_service import NotificationCreationResult
from src.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _response_from_result(
    result: NotificationCreationResult,
    response: Response,
) -> NotificationResponse:
    """Build an HTTP response for an idempotent creation result."""
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return NotificationResponse.model_validate(result.notification)


@router.post(
    "",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_notification(
    data: NotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist a notification event idempotently."""
    result = NotificationService(db).create_notification(data)
    return _response_from_result(result, response)


@router.post(
    "/order-status-changed",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order_status_changed_notification(
    data: OrderStatusChangedNotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist an order status change notification event."""
    result = NotificationService(db).create_order_status_changed_notification(data)
    return _response_from_result(result, response)


@router.post(
    "/low-stock",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_low_stock_notification(
    data: LowStockNotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist a low stock notification event."""
    result = NotificationService(db).create_low_stock_notification(data)
    return _response_from_result(result, response)


@router.post(
    "/out-of-stock",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_out_of_stock_notification(
    data: OutOfStockNotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist an out-of-stock notification event."""
    result = NotificationService(db).create_out_of_stock_notification(data)
    return _response_from_result(result, response)
