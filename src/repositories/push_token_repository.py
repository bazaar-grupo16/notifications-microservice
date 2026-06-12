"""Database access for notification push tokens."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification_push_token import NotificationPushToken


class PushTokenRepository:
    """Repository for Expo push token persistence operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_token(
        self, expo_push_token: str
    ) -> NotificationPushToken | None:
        """Return a push token row by token value."""
        stmt = select(NotificationPushToken).where(
            NotificationPushToken.expo_push_token == expo_push_token
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_enabled_by_recipient(
        self, recipient_id: str
    ) -> list[NotificationPushToken]:
        """Return enabled tokens for a recipient."""
        stmt = select(NotificationPushToken).where(
            NotificationPushToken.recipient_id == recipient_id,
            NotificationPushToken.enabled.is_(True),
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def save(
        self, push_token: NotificationPushToken
    ) -> NotificationPushToken:
        """Persist a push token."""
        self._db.add(push_token)
        await self._db.commit()
        await self._db.refresh(push_token)
        return push_token
