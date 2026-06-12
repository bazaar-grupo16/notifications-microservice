"""Tests for persisted notification creation and processing."""

import pytest
from sqlalchemy import delete, func, select
from uuid import uuid4

import httpx
import pytest_asyncio

from src.core.database import AsyncSessionLocal, engine
from src.core.observability import CORRELATION_ID_HEADER
from src.models.notification import Notification
from src.models.notification_push_token import NotificationPushToken
from src.services.notification_worker import (
    ExpoPushNotificationSender,
    process_pending_notifications,
)


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _clean_notifications() -> None:
    """Ensure each test starts without queued notifications."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification))
        await db.execute(delete(NotificationPushToken))
        await db.commit()
    await engine.dispose()


def _notification_payload(idempotency_key: str = "order:123:status:shipped") -> dict:
    """Return a valid notification request body."""
    return {
        "idempotency_key": idempotency_key,
        "type": "order_status_changed",
        "recipient_id": "buyer-123",
        "title": "Orden actualizada",
        "body": "Tu orden cambió de estado.",
        "payload": {"order_id": "123", "status": "shipped"},
    }


async def _count_notifications() -> int:
    """Return the number of persisted notifications."""
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(func.count()).select_from(Notification))
        ).scalar_one()


async def _get_notification(notification_id: int) -> Notification:
    """Load a notification by id."""
    async with AsyncSessionLocal() as db:
        notification = await db.get(Notification, notification_id)
        assert notification is not None
        return notification


class TestCreateNotification:
    """Notification ingestion endpoint tests."""

    async def test_creates_pending_notification(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/notifications", json=_notification_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["idempotency_key"] == "order:123:status:shipped"
        assert body["type"] == "order_status_changed"
        assert body["recipient_id"] == "buyer-123"
        assert body["correlation_id"]
        assert body["status"] == "pending"
        assert body["attempts"] == 0
        assert body["sent_at"] is None
        assert body["read_at"] is None
        assert body["is_read"] is False

    async def test_persists_inbound_correlation_id(self, client: httpx.AsyncClient) -> None:
        correlation_id = "notification-create-correlation"

        response = await client.post(
            "/notifications",
            json=_notification_payload("order:123:status:packed"),
            headers={CORRELATION_ID_HEADER: correlation_id},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["correlation_id"] == correlation_id

        notification = await _get_notification(body["id"])
        assert notification.correlation_id == correlation_id

    async def test_is_idempotent_by_idempotency_key(self, client: httpx.AsyncClient) -> None:
        payload = _notification_payload("order:456:status:paid")

        first_response = await client.post(
            "/notifications",
            json=payload,
            headers={CORRELATION_ID_HEADER: "first-correlation-id"},
        )
        second_response = await client.post(
            "/notifications",
            json=payload,
            headers={CORRELATION_ID_HEADER: "second-correlation-id"},
        )

        assert first_response.status_code == 201
        assert second_response.status_code == 200
        assert first_response.json()["id"] == second_response.json()["id"]
        assert first_response.json()["correlation_id"] == "first-correlation-id"
        assert second_response.json()["correlation_id"] == "first-correlation-id"
        assert await _count_notifications() == 1

    async def test_rejects_invalid_payload(self, client: httpx.AsyncClient) -> None:
        payload = _notification_payload()
        payload.pop("idempotency_key")

        response = await client.post("/notifications", json=payload)

        assert response.status_code == 422


class TestBusinessNotificationEndpoints:
    """Specific notification contracts for TP acceptance criteria."""

    async def test_creates_order_status_changed_notification(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        payload = {
            "order_id": "order-123",
            "buyer_id": "buyer-123",
            "new_status": "EN_PREPARACION",
            "tracking_code": "TRACK-123",
        }

        response = await client.post("/notifications/order-status-changed", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["type"] == "order_status_changed"
        assert body["recipient_id"] == "buyer-123"
        assert body["idempotency_key"] == "order:order-123:status:EN_PREPARACION"
        assert body["payload"]["order_id"] == "order-123"
        assert body["payload"]["new_status"] == "EN_PREPARACION"
        assert body["payload"]["tracking_code"] == "TRACK-123"
        assert body["payload"]["deep_link"] == "bazaar://orders/order-123"

    async def test_order_status_changed_is_idempotent(self, client: httpx.AsyncClient) -> None:
        payload = {
            "order_id": "order-456",
            "buyer_id": "buyer-456",
            "new_status": "ENVIADA",
        }

        first_response = await client.post("/notifications/order-status-changed", json=payload)
        second_response = await client.post("/notifications/order-status-changed", json=payload)

        assert first_response.status_code == 201
        assert second_response.status_code == 200
        assert first_response.json()["id"] == second_response.json()["id"]
        assert await _count_notifications() == 1

    async def test_creates_low_stock_notification(self, client: httpx.AsyncClient) -> None:
        payload = {
            "seller_id": "seller-123",
            "product_id": "product-123",
            "product_name": "Auriculares",
            "current_stock": 3,
            "threshold": 5,
        }

        response = await client.post("/notifications/low-stock", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["type"] == "low_stock"
        assert body["recipient_id"] == "seller-123"
        assert body["idempotency_key"] == "low_stock:seller-123:product-123:5"
        assert body["payload"]["product_name"] == "Auriculares"
        assert body["payload"]["current_stock"] == 3
        assert body["payload"]["threshold"] == 5
        assert body["payload"]["deep_link"] == "bazaar://seller/products/product-123"

    async def test_low_stock_rejects_stock_above_threshold(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        payload = {
            "seller_id": "seller-123",
            "product_id": "product-123",
            "product_name": "Auriculares",
            "current_stock": 5,
            "threshold": 5,
        }

        response = await client.post("/notifications/low-stock", json=payload)

        assert response.status_code == 422

    async def test_low_stock_is_idempotent(self, client: httpx.AsyncClient) -> None:
        payload = {
            "seller_id": "seller-456",
            "product_id": "product-456",
            "product_name": "Mouse",
            "current_stock": 1,
            "threshold": 5,
        }

        first_response = await client.post("/notifications/low-stock", json=payload)
        second_response = await client.post("/notifications/low-stock", json=payload)

        assert first_response.status_code == 201
        assert second_response.status_code == 200
        assert first_response.json()["id"] == second_response.json()["id"]
        assert await _count_notifications() == 1

    async def test_creates_out_of_stock_notification(self, client: httpx.AsyncClient) -> None:
        payload = {
            "seller_id": "seller-789",
            "product_id": "product-789",
            "product_name": "Teclado",
            "current_stock": 0,
        }

        response = await client.post("/notifications/out-of-stock", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["type"] == "out_of_stock"
        assert body["recipient_id"] == "seller-789"
        assert body["idempotency_key"] == "out_of_stock:seller-789:product-789"
        assert body["payload"]["current_stock"] == 0
        assert body["payload"]["deep_link"] == "bazaar://seller/products/product-789"

    async def test_out_of_stock_requires_zero_stock(self, client: httpx.AsyncClient) -> None:
        payload = {
            "seller_id": "seller-789",
            "product_id": "product-789",
            "product_name": "Teclado",
            "current_stock": 1,
        }

        response = await client.post("/notifications/out-of-stock", json=payload)

        assert response.status_code == 422


class TestRecipientNotificationReadModel:
    """Recipient-facing notification history endpoints."""

    async def test_lists_only_authenticated_recipient_notifications(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        user_id = str(uuid4())
        other_user_id = str(uuid4())
        first_response = await client.post(
            "/notifications",
            json={
                **_notification_payload("order:1:status:confirmed"),
                "recipient_id": user_id,
                "title": "Primera",
            },
        )
        second_response = await client.post(
            "/notifications",
            json={
                **_notification_payload("order:2:status:confirmed"),
                "recipient_id": user_id,
                "title": "Segunda",
            },
        )
        await client.post(
            "/notifications",
            json={
                **_notification_payload("order:3:status:confirmed"),
                "recipient_id": other_user_id,
            },
        )

        response = await client.get(
            "/notifications/me",
            headers={"X-User-Id": user_id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["limit"] == 20
        assert body["offset"] == 0
        assert [item["id"] for item in body["data"]] == [
            second_response.json()["id"],
            first_response.json()["id"],
        ]
        assert all(item["recipient_id"] == user_id for item in body["data"])
        assert all(item["is_read"] is False for item in body["data"])

    async def test_lists_notifications_with_pagination(self, client: httpx.AsyncClient) -> None:
        user_id = str(uuid4())
        first_response = await client.post(
            "/notifications",
            json={
                **_notification_payload("order:4:status:confirmed"),
                "recipient_id": user_id,
            },
        )
        second_response = await client.post(
            "/notifications",
            json={
                **_notification_payload("order:5:status:confirmed"),
                "recipient_id": user_id,
            },
        )

        response = await client.get(
            "/notifications/me?limit=1&offset=1",
            headers={"X-User-Id": user_id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["limit"] == 1
        assert body["offset"] == 1
        assert [item["id"] for item in body["data"]] == [
            first_response.json()["id"],
        ]
        assert second_response.json()["id"] != first_response.json()["id"]

    async def test_unread_count(self, client: httpx.AsyncClient) -> None:
        user_id = str(uuid4())
        await client.post(
            "/notifications",
            json={
                **_notification_payload("order:6:status:confirmed"),
                "recipient_id": user_id,
            },
        )
        read_response = await client.post(
            "/notifications",
            json={
                **_notification_payload("order:7:status:confirmed"),
                "recipient_id": user_id,
            },
        )
        await client.patch(
            f"/notifications/{read_response.json()['id']}/read",
            headers={"X-User-Id": user_id},
        )

        response = await client.get(
            "/notifications/me/unread-count",
            headers={"X-User-Id": user_id},
        )

        assert response.status_code == 200
        assert response.json() == {"unread_count": 1}

    async def test_marks_notification_as_read_idempotently(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        user_id = str(uuid4())
        create_response = await client.post(
            "/notifications",
            json={
                **_notification_payload("order:8:status:confirmed"),
                "recipient_id": user_id,
            },
        )
        notification_id = create_response.json()["id"]

        first_response = await client.patch(
            f"/notifications/{notification_id}/read",
            headers={"X-User-Id": user_id},
        )
        second_response = await client.patch(
            f"/notifications/{notification_id}/read",
            headers={"X-User-Id": user_id},
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert first_response.json()["is_read"] is True
        assert second_response.json()["is_read"] is True
        assert first_response.json()["read_at"] == second_response.json()["read_at"]

    async def test_cannot_mark_another_recipient_notification_as_read(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        owner_id = str(uuid4())
        other_user_id = str(uuid4())
        create_response = await client.post(
            "/notifications",
            json={
                **_notification_payload("order:9:status:confirmed"),
                "recipient_id": owner_id,
            },
        )

        response = await client.patch(
            f"/notifications/{create_response.json()['id']}/read",
            headers={"X-User-Id": other_user_id},
        )

        assert response.status_code == 404

    async def test_marks_all_notifications_as_read(self, client: httpx.AsyncClient) -> None:
        user_id = str(uuid4())
        other_user_id = str(uuid4())
        for index in range(2):
            await client.post(
                "/notifications",
                json={
                    **_notification_payload(f"order:read-all-{index}:status:confirmed"),
                    "recipient_id": user_id,
                },
            )
        await client.post(
            "/notifications",
            json={
                **_notification_payload("order:read-all-other:status:confirmed"),
                "recipient_id": other_user_id,
            },
        )

        response = await client.patch(
            "/notifications/read-all",
            headers={"X-User-Id": user_id},
        )
        unread_response = await client.get(
            "/notifications/me/unread-count",
            headers={"X-User-Id": user_id},
        )
        other_unread_response = await client.get(
            "/notifications/me/unread-count",
            headers={"X-User-Id": other_user_id},
        )

        assert response.status_code == 200
        assert response.json() == {"updated_count": 2}
        assert unread_response.json() == {"unread_count": 0}
        assert other_unread_response.json() == {"unread_count": 1}

    async def test_requires_authenticated_user_header(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/notifications/me")

        assert response.status_code == 401


class TestPushTokens:
    """Push token registration endpoint tests."""

    async def test_registers_push_token_for_authenticated_recipient(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        user_id = str(uuid4())

        response = await client.post(
            "/notifications/push-tokens",
            json={
                "expo_push_token": "ExponentPushToken[token-1]",
                "platform": "android",
            },
            headers={"X-User-Id": user_id},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["recipient_id"] == user_id
        assert body["expo_push_token"] == "ExponentPushToken[token-1]"
        assert body["platform"] == "android"
        assert body["enabled"] is True

    async def test_requires_authentication_to_register_push_token(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        response = await client.post(
            "/notifications/push-tokens",
            json={
                "expo_push_token": "ExponentPushToken[token-2]",
                "platform": "ios",
            },
        )

        assert response.status_code == 401

    async def test_registering_same_token_is_idempotent(self, client: httpx.AsyncClient) -> None:
        user_id = str(uuid4())
        payload = {
            "expo_push_token": "ExponentPushToken[token-3]",
            "platform": "android",
        }

        first_response = await client.post(
            "/notifications/push-tokens",
            json=payload,
            headers={"X-User-Id": user_id},
        )
        second_response = await client.post(
            "/notifications/push-tokens",
            json=payload,
            headers={"X-User-Id": user_id},
        )

        assert first_response.status_code == 201
        assert second_response.status_code == 201
        assert first_response.json()["id"] == second_response.json()["id"]

    async def test_disables_recipient_push_token(self, client: httpx.AsyncClient) -> None:
        user_id = str(uuid4())
        token = "ExponentPushToken[token-4]"
        await client.post(
            "/notifications/push-tokens",
            json={"expo_push_token": token, "platform": "android"},
            headers={"X-User-Id": user_id},
        )

        response = await client.delete(
            f"/notifications/push-tokens/{token}",
            headers={"X-User-Id": user_id},
        )

        assert response.status_code == 200
        assert response.json() == {"disabled": True}

    async def test_does_not_disable_another_recipient_token(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        owner_id = str(uuid4())
        other_user_id = str(uuid4())
        token = "ExponentPushToken[token-5]"
        await client.post(
            "/notifications/push-tokens",
            json={"expo_push_token": token, "platform": "android"},
            headers={"X-User-Id": owner_id},
        )

        response = await client.delete(
            f"/notifications/push-tokens/{token}",
            headers={"X-User-Id": other_user_id},
        )

        assert response.status_code == 200
        assert response.json() == {"disabled": False}


class TestNotificationWorker:
    """Pending notification worker tests."""

    async def test_marks_pending_notification_as_sent(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/notifications",
            json=_notification_payload("order:789:status:delivered"),
        )
        notification_id = response.json()["id"]

        async with AsyncSessionLocal() as db:
            processed = await process_pending_notifications(db)

        notification = await _get_notification(notification_id)
        assert processed == 1
        assert notification.correlation_id == response.json()["correlation_id"]
        assert notification.status == "sent"
        assert notification.attempts == 1
        assert notification.last_error is None
        assert notification.next_retry_at is None
        assert notification.sent_at is not None

    async def test_reprograms_notification_when_sender_fails_and_attempts_remain(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        class FailingSender:
            async def send(self, notification: Notification) -> None:
                raise RuntimeError("push provider unavailable")

        response = await client.post(
            "/notifications",
            json=_notification_payload("low_stock:seller-1:product-1:3"),
        )
        notification_id = response.json()["id"]

        async with AsyncSessionLocal() as db:
            processed = await process_pending_notifications(
                db,
                max_attempts=3,
                retry_delay_seconds=30,
                sender=FailingSender(),
            )

        notification = await _get_notification(notification_id)
        assert processed == 1
        assert notification.correlation_id == response.json()["correlation_id"]
        assert notification.status == "pending"
        assert notification.attempts == 1
        assert notification.last_error == "push provider unavailable"
        assert notification.next_retry_at is not None
        assert notification.sent_at is None

    async def test_marks_notification_as_failed_when_max_attempts_is_reached(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        class FailingSender:
            async def send(self, notification: Notification) -> None:
                raise RuntimeError("push provider unavailable")

        response = await client.post(
            "/notifications",
            json=_notification_payload("low_stock:seller-2:product-2:3"),
        )
        notification_id = response.json()["id"]

        async with AsyncSessionLocal() as db:
            processed = await process_pending_notifications(
                db,
                max_attempts=1,
                sender=FailingSender(),
            )

        notification = await _get_notification(notification_id)
        assert processed == 1
        assert notification.status == "failed"
        assert notification.attempts == 1
        assert notification.last_error == "push provider unavailable"
        assert notification.next_retry_at is None
        assert notification.sent_at is None

    async def test_expo_sender_marks_notification_as_sent(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        user_id = str(uuid4())
        await client.post(
            "/notifications/push-tokens",
            json={
                "expo_push_token": "ExponentPushToken[token-6]",
                "platform": "android",
            },
            headers={"X-User-Id": user_id},
        )
        response = await client.post(
            "/notifications",
            json={**_notification_payload("order:10:status:sent"), "recipient_id": user_id},
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"data": [{"status": "ok", "id": "ticket-1"}]},
                request=request,
            )
        )
        async with httpx.AsyncClient(transport=transport) as expo_client:
            async with AsyncSessionLocal() as db:
                processed = await process_pending_notifications(
                    db,
                    sender=ExpoPushNotificationSender(db, expo_client),
                )

        notification = await _get_notification(response.json()["id"])
        assert processed == 1
        assert notification.status == "sent"

    async def test_expo_sender_disables_permanent_invalid_token(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        user_id = str(uuid4())
        token = "ExponentPushToken[token-7]"
        await client.post(
            "/notifications/push-tokens",
            json={"expo_push_token": token, "platform": "android"},
            headers={"X-User-Id": user_id},
        )
        response = await client.post(
            "/notifications",
            json={**_notification_payload("order:11:status:sent"), "recipient_id": user_id},
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "status": "error",
                            "message": "Device not registered",
                            "details": {"error": "DeviceNotRegistered"},
                        }
                    ]
                },
                request=request,
            )
        )
        async with httpx.AsyncClient(transport=transport) as expo_client:
            async with AsyncSessionLocal() as db:
                processed = await process_pending_notifications(
                    db,
                    sender=ExpoPushNotificationSender(db, expo_client),
                )
                stored_token = (
                    await db.execute(
                        select(NotificationPushToken).where(
                            NotificationPushToken.expo_push_token == token
                        )
                    )
                ).scalar_one()

        notification = await _get_notification(response.json()["id"])
        assert processed == 1
        assert notification.status == "sent"
        assert stored_token.enabled is False

    async def test_expo_sender_retries_transient_errors(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        user_id = str(uuid4())
        await client.post(
            "/notifications/push-tokens",
            json={
                "expo_push_token": "ExponentPushToken[token-8]",
                "platform": "android",
            },
            headers={"X-User-Id": user_id},
        )
        response = await client.post(
            "/notifications",
            json={**_notification_payload("order:12:status:sent"), "recipient_id": user_id},
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "status": "error",
                            "message": "Expo temporarily unavailable",
                        }
                    ]
                },
                request=request,
            )
        )
        async with httpx.AsyncClient(transport=transport) as expo_client:
            async with AsyncSessionLocal() as db:
                processed = await process_pending_notifications(
                    db,
                    sender=ExpoPushNotificationSender(db, expo_client),
                )

        notification = await _get_notification(response.json()["id"])
        assert processed == 1
        assert notification.status == "pending"
        assert notification.last_error == "Expo temporarily unavailable"
        assert notification.next_retry_at is not None
