"""Lightweight worker for processing pending notifications."""

import logging
from datetime import timedelta
from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.utils import utc_now
from src.models.notification import Notification
from src.repositories.push_token_repository import PushTokenRepository
from src.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)


def _notification_log_context(notification: Notification) -> dict[str, object]:
    """Return common structured fields for notification logs."""
    return {
        "correlation_id": notification.correlation_id,
        "notification_id": notification.id,
        "notification_type": notification.notification_type,
        "recipient_id": notification.recipient_id,
        "status": notification.status,
        "attempts": notification.attempts,
    }


class NotificationSender(Protocol):
    """Sender interface used by the worker."""

    async def send(self, notification: Notification) -> None:
        """Send a notification."""


class SimulatedNotificationSender:
    """Development sender used until push integration is added."""

    async def send(self, notification: Notification) -> None:
        """Simulate notification delivery."""
        logger.info(
            "Simulated notification delivery",
            extra=_notification_log_context(notification),
        )


class ExpoPushNotificationSender:
    """Send notifications through Expo Push Notifications."""

    _PERMANENT_TOKEN_ERRORS = {
        "DeviceNotRegistered",
        "InvalidCredentials",
        "MessageTooBig",
        "MessageRateExceeded",
    }

    def __init__(
        self,
        db: AsyncSession,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._db = db
        self._push_tokens = PushTokenRepository(db)
        self._settings = get_settings()
        self._http_client = http_client

    async def send(self, notification: Notification) -> None:
        """Send a notification to all enabled recipient tokens."""
        tokens = await self._push_tokens.list_enabled_by_recipient(
            notification.recipient_id
        )
        if not tokens:
            logger.info(
                "No enabled push tokens for notification recipient",
                extra=_notification_log_context(notification),
            )
            return

        messages = [
            {
                "to": token.expo_push_token,
                "title": notification.title,
                "body": notification.body,
                "data": notification.payload,
            }
            for token in tokens
        ]
        headers = {"Content-Type": "application/json"}
        if self._settings.EXPO_PUSH_ACCESS_TOKEN:
            headers["Authorization"] = (
                f"Bearer {self._settings.EXPO_PUSH_ACCESS_TOKEN}"
            )

        client = self._http_client or httpx.AsyncClient()
        try:
            response = await client.post(
                self._settings.EXPO_PUSH_API_URL,
                json=messages,
                headers=headers,
                timeout=5.0,
            )
        finally:
            if self._http_client is None:
                await client.aclose()
        response.raise_for_status()
        payload = response.json()
        tickets = payload.get("data", payload)
        if isinstance(tickets, dict):
            tickets = [tickets]
        if not isinstance(tickets, list):
            raise RuntimeError("Unexpected Expo push response shape")

        transient_errors: list[str] = []
        for token, ticket in zip(tokens, tickets, strict=False):
            if not isinstance(ticket, dict):
                transient_errors.append("invalid-ticket")
                continue
            if ticket.get("status") == "ok":
                continue

            details = ticket.get("details") or {}
            error_code = details.get("error") if isinstance(details, dict) else None
            message = str(ticket.get("message") or error_code or "Expo push failed")
            if error_code in self._PERMANENT_TOKEN_ERRORS:
                token.enabled = False
                await self._push_tokens.save(token)
                logger.warning(
                    "Disabled push token after permanent Expo error",
                    extra={
                        **_notification_log_context(notification),
                        "expo_error": error_code,
                    },
                )
            else:
                transient_errors.append(message)

        if transient_errors:
            raise RuntimeError("; ".join(transient_errors))


def _build_sender(db: AsyncSession) -> NotificationSender:
    """Build the configured notification sender."""
    if get_settings().NOTIFICATION_SENDER.lower() == "expo":
        return ExpoPushNotificationSender(db)
    return SimulatedNotificationSender()


async def process_pending_notifications(
    db: AsyncSession,
    *,
    limit: int = 10,
    max_attempts: int = 3,
    retry_delay_seconds: float = 30.0,
    sender: NotificationSender | None = None,
) -> int:
    """Process pending notifications and return how many were handled."""
    repository = NotificationRepository(db)
    notification_sender = sender or _build_sender(db)
    notifications = await repository.list_pending(limit=limit, ready_at=utc_now())

    processed = 0
    for notification in notifications:
        notification.attempts += 1
        notification.last_error = None
        notification.next_retry_at = None

        try:
            await notification_sender.send(notification)
        except Exception as exc:
            notification.last_error = str(exc)
            if notification.attempts >= max_attempts:
                notification.status = "failed"
            else:
                notification.status = "pending"
                notification.next_retry_at = utc_now() + timedelta(
                    seconds=retry_delay_seconds
                )
            logger.exception(
                "Notification processing failed",
                extra=_notification_log_context(notification),
            )
        else:
            notification.status = "sent"
            notification.sent_at = utc_now()
            logger.info(
                "Notification processing succeeded",
                extra=_notification_log_context(notification),
            )

        await repository.save(notification)
        processed += 1

    return processed
