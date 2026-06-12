"""Business rules for recipient push token registration."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification_push_token import NotificationPushToken
from src.repositories.push_token_repository import PushTokenRepository
from src.schemas.notification import PushTokenCreate


class PushTokenService:
    """Application service for Expo push token registration."""

    def __init__(self, db: AsyncSession) -> None:
        self._repository = PushTokenRepository(db)

    async def register_push_token(
        self,
        recipient_id: str,
        data: PushTokenCreate,
    ) -> NotificationPushToken:
        """Register or reactivate a recipient's Expo push token."""
        existing = await self._repository.get_by_token(data.expo_push_token)
        if existing is not None:
            existing.recipient_id = recipient_id
            existing.platform = data.platform
            existing.enabled = True
            return await self._repository.save(existing)

        return await self._repository.save(
            NotificationPushToken(
                recipient_id=recipient_id,
                expo_push_token=data.expo_push_token,
                platform=data.platform,
                enabled=True,
            )
        )

    async def disable_push_token(
        self, recipient_id: str, expo_push_token: str
    ) -> bool:
        """Disable a recipient-owned push token if it exists."""
        existing = await self._repository.get_by_token(expo_push_token)
        if existing is None or existing.recipient_id != recipient_id:
            return False
        if existing.enabled:
            existing.enabled = False
            await self._repository.save(existing)
        return True
