"""HTTP routes for internal notification events."""

from fastapi import APIRouter, HTTPException, Query, Response, status

from src.core.dependencies import CurrentUserId, DbSession
from src.schemas.notification import (
    LowStockNotificationCreate,
    NotificationListResponse,
    NotificationCreate,
    NotificationResponse,
    NotificationsReadAllResponse,
    NotificationUnreadCountResponse,
    OrderStatusChangedNotificationCreate,
    OrderItemStatusChangedNotificationCreate,
    OutOfStockNotificationCreate,
    PushTokenCreate,
    PushTokenDeleteResponse,
    PushTokenResponse,
)
from src.services.notification_service import NotificationCreationResult
from src.services.notification_service import NotificationService
from src.services.push_token_service import PushTokenService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _response_from_result(
    result: NotificationCreationResult,
    response: Response,
) -> NotificationResponse:
    """Build an HTTP response for an idempotent creation result."""
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return NotificationResponse.model_validate(result.notification)


@router.get(
    "/me",
    response_model=NotificationListResponse,
)
async def list_my_notifications(
    db: DbSession,
    current_user_id: CurrentUserId,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> NotificationListResponse:
    """List notifications for the authenticated recipient."""
    notifications, total = await NotificationService(
        db
    ).list_notifications_for_recipient(
        str(current_user_id),
        limit=limit,
        offset=offset,
    )
    return NotificationListResponse(
        data=[NotificationResponse.model_validate(item) for item in notifications],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/me/unread-count",
    response_model=NotificationUnreadCountResponse,
)
async def get_my_unread_count(
    db: DbSession,
    current_user_id: CurrentUserId,
) -> NotificationUnreadCountResponse:
    """Return unread notifications count for the authenticated recipient."""
    unread_count = await NotificationService(db).count_unread_for_recipient(
        str(current_user_id)
    )
    return NotificationUnreadCountResponse(unread_count=unread_count)


@router.patch(
    "/read-all",
    response_model=NotificationsReadAllResponse,
)
async def mark_all_my_notifications_as_read(
    db: DbSession,
    current_user_id: CurrentUserId,
) -> NotificationsReadAllResponse:
    """Mark all authenticated recipient notifications as read."""
    updated_count = await NotificationService(db).mark_all_notifications_as_read(
        str(current_user_id)
    )
    return NotificationsReadAllResponse(updated_count=updated_count)


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
)
async def mark_my_notification_as_read(
    notification_id: int,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> NotificationResponse:
    """Mark one authenticated recipient notification as read."""
    notification = await NotificationService(db).mark_notification_as_read(
        notification_id,
        str(current_user_id),
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return NotificationResponse.model_validate(notification)


@router.post(
    "/push-tokens",
    response_model=PushTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_my_push_token(
    data: PushTokenCreate,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> PushTokenResponse:
    """Register or reactivate an Expo push token for the authenticated recipient."""
    push_token = await PushTokenService(db).register_push_token(
        str(current_user_id),
        data,
    )
    return PushTokenResponse.model_validate(push_token)


@router.delete(
    "/push-tokens/{expo_push_token}",
    response_model=PushTokenDeleteResponse,
)
async def disable_my_push_token(
    expo_push_token: str,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> PushTokenDeleteResponse:
    """Disable a recipient-owned Expo push token."""
    disabled = await PushTokenService(db).disable_push_token(
        str(current_user_id),
        expo_push_token,
    )
    return PushTokenDeleteResponse(disabled=disabled)


@router.post(
    "",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_notification(
    data: NotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist a notification event idempotently."""
    result = await NotificationService(db).create_notification(data)
    return _response_from_result(result, response)


@router.post(
    "/order-status-changed",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_status_changed_notification(
    data: OrderStatusChangedNotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist an order status change notification event."""
    result = await NotificationService(db).create_order_status_changed_notification(
        data
    )
    return _response_from_result(result, response)


@router.post(
    "/order-item-status-changed",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_item_status_changed_notification(
    data: OrderItemStatusChangedNotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist an order item status change notification event."""
    result = await NotificationService(
        db
    ).create_order_item_status_changed_notification(data)
    return _response_from_result(result, response)


@router.post(
    "/low-stock",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_low_stock_notification(
    data: LowStockNotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist a low stock notification event."""
    result = await NotificationService(db).create_low_stock_notification(data)
    return _response_from_result(result, response)


@router.post(
    "/out-of-stock",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_out_of_stock_notification(
    data: OutOfStockNotificationCreate,
    response: Response,
    db: DbSession,
) -> NotificationResponse:
    """Persist an out-of-stock notification event."""
    result = await NotificationService(db).create_out_of_stock_notification(data)
    return _response_from_result(result, response)
