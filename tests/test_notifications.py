"""Tests for persisted notification creation and processing."""

import pytest
from sqlalchemy import delete, func, select

from fastapi.testclient import TestClient

from src.core.database import SessionLocal
from src.core.observability import CORRELATION_ID_HEADER
from src.models.notification import Notification
from src.services.notification_worker import process_pending_notifications


@pytest.fixture(autouse=True)
def _clean_notifications() -> None:
    """Ensure each test starts without queued notifications."""
    with SessionLocal() as db:
        db.execute(delete(Notification))
        db.commit()


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


def _count_notifications() -> int:
    """Return the number of persisted notifications."""
    with SessionLocal() as db:
        return db.execute(select(func.count()).select_from(Notification)).scalar_one()


def _get_notification(notification_id: int) -> Notification:
    """Load a notification by id."""
    with SessionLocal() as db:
        notification = db.get(Notification, notification_id)
        assert notification is not None
        return notification


class TestCreateNotification:
    """Notification ingestion endpoint tests."""

    def test_creates_pending_notification(self, client: TestClient) -> None:
        response = client.post("/notifications", json=_notification_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["idempotency_key"] == "order:123:status:shipped"
        assert body["type"] == "order_status_changed"
        assert body["recipient_id"] == "buyer-123"
        assert body["correlation_id"]
        assert body["status"] == "pending"
        assert body["attempts"] == 0
        assert body["sent_at"] is None

    def test_persists_inbound_correlation_id(self, client: TestClient) -> None:
        correlation_id = "notification-create-correlation"

        response = client.post(
            "/notifications",
            json=_notification_payload("order:123:status:packed"),
            headers={CORRELATION_ID_HEADER: correlation_id},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["correlation_id"] == correlation_id

        notification = _get_notification(body["id"])
        assert notification.correlation_id == correlation_id

    def test_is_idempotent_by_idempotency_key(self, client: TestClient) -> None:
        payload = _notification_payload("order:456:status:paid")

        first_response = client.post(
            "/notifications",
            json=payload,
            headers={CORRELATION_ID_HEADER: "first-correlation-id"},
        )
        second_response = client.post(
            "/notifications",
            json=payload,
            headers={CORRELATION_ID_HEADER: "second-correlation-id"},
        )

        assert first_response.status_code == 201
        assert second_response.status_code == 200
        assert first_response.json()["id"] == second_response.json()["id"]
        assert first_response.json()["correlation_id"] == "first-correlation-id"
        assert second_response.json()["correlation_id"] == "first-correlation-id"
        assert _count_notifications() == 1

    def test_rejects_invalid_payload(self, client: TestClient) -> None:
        payload = _notification_payload()
        payload.pop("idempotency_key")

        response = client.post("/notifications", json=payload)

        assert response.status_code == 422


class TestNotificationWorker:
    """Pending notification worker tests."""

    def test_marks_pending_notification_as_sent(self, client: TestClient) -> None:
        response = client.post(
            "/notifications",
            json=_notification_payload("order:789:status:delivered"),
        )
        notification_id = response.json()["id"]

        with SessionLocal() as db:
            processed = process_pending_notifications(db)

        notification = _get_notification(notification_id)
        assert processed == 1
        assert notification.correlation_id == response.json()["correlation_id"]
        assert notification.status == "sent"
        assert notification.attempts == 1
        assert notification.last_error is None
        assert notification.sent_at is not None

    def test_marks_notification_as_failed_when_sender_fails(
        self,
        client: TestClient,
    ) -> None:
        class FailingSender:
            def send(self, notification: Notification) -> None:
                raise RuntimeError("push provider unavailable")

        response = client.post(
            "/notifications",
            json=_notification_payload("low_stock:seller-1:product-1:3"),
        )
        notification_id = response.json()["id"]

        with SessionLocal() as db:
            processed = process_pending_notifications(db, sender=FailingSender())

        notification = _get_notification(notification_id)
        assert processed == 1
        assert notification.correlation_id == response.json()["correlation_id"]
        assert notification.status == "failed"
        assert notification.attempts == 1
        assert notification.last_error == "push provider unavailable"
        assert notification.sent_at is None
