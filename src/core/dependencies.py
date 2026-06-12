"""
FastAPI dependencies for dependency injection.

Add shared dependencies here (e.g. database sessions, auth context).
"""

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a SQLAlchemy session and ensure it is closed afterwards."""
    async with AsyncSessionLocal() as db:
        yield db


def _get_current_user_id(x_user_id: str | None = Header(None)) -> UUID:
    """Extract the authenticated user id injected by the gateway."""
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id header",
        )
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-User-Id header",
        )


# Re-usable annotated dependency for route signatures.
DbSession = Annotated[AsyncSession, Depends(_get_db)]
CurrentUserId = Annotated[UUID, Depends(_get_current_user_id)]
