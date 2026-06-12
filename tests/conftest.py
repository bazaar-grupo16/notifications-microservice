"""
Shared asynchronous pytest fixtures for the test suite.

Tests run against a real PostgreSQL database provided by
``docker-compose.test.yml``.
"""

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal, Base, engine
from src.main import app


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_database() -> AsyncIterator[None]:
    """Create all tables before the session and tear them down after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield an isolated async database session."""
    try:
        async with AsyncSessionLocal() as session:
            yield session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Return an asynchronous HTTP client bound to the FastAPI application."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client
