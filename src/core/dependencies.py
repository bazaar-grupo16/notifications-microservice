"""
FastAPI dependencies for dependency injection.

Add shared dependencies here (e.g. database sessions, auth context).
"""

from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import SessionLocal


def _get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session and ensure it is closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
DbSession = Annotated[Session, Depends(_get_db)]
CurrentUserId = Annotated[UUID, Depends(_get_current_user_id)]
