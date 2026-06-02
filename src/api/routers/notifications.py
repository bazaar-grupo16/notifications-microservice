"""HTTP routes for internal notification events."""

from fastapi import APIRouter, Response, status

from src.core.dependencies import DbSession
from src.schemas.notification import NotificationCreate, NotificationResponse
from src.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


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
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return NotificationResponse.model_validate(result.notification)
