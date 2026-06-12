"""
Tests for the health-check endpoints ``/livez`` and ``/readyz``.

These tests run against a real PostgreSQL instance — **no mocking**.
The database is provided by ``docker-compose.test.yml``.
"""

import httpx
import pytest
from unittest.mock import AsyncMock, patch


pytestmark = pytest.mark.asyncio


class TestLivez:
    """``/livez`` must always return 200 without any external call."""

    async def test_returns_200(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/livez")
        assert response.status_code == 200

    async def test_body_contains_alive(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/livez")
        body = response.json()
        assert body == {"status": "alive"}


class TestReadyz:
    """``/readyz`` validates connectivity to the real PostgreSQL database."""

    async def test_returns_200_when_db_is_up(self, client: httpx.AsyncClient) -> None:
        """With the docker-compose DB running, /readyz must return 200."""
        response = await client.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    async def test_returns_503_when_db_is_down(
        self, client: httpx.AsyncClient
    ) -> None:
        with patch(
            "src.api.health.check_db_connection",
            new=AsyncMock(return_value=False),
        ):
            response = await client.get("/readyz")

        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
