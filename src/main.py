"""
Bazaar Microservice — Application entry-point.

Creates the FastAPI application, registers routers, and configures
structured logging.  Database tables are created on startup via the
ORM metadata (suitable for development; use Alembic migrations in
production).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.health import router as health_router
from src.api.routers.notifications import router as notifications_router
from src.core.config import get_settings
from src.core.database import AsyncSessionLocal, Base, engine, wait_for_db
from src.core.logging import setup_logging
from src.core.observability import CorrelationIdMiddleware
from src.core.telemetry import initialize_prometheus_metrics, router as metrics_router
import src.models.notification  # noqa: F401
import src.models.notification_push_token  # noqa: F401
from src.services.notification_worker import process_pending_notifications

settings = get_settings()
logger = logging.getLogger(__name__)

initialize_prometheus_metrics()


async def _notification_worker_loop() -> None:
    """Periodically process pending notifications in the app process."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                processed = await process_pending_notifications(
                    db,
                    limit=settings.NOTIFICATION_WORKER_BATCH_SIZE,
                    max_attempts=settings.NOTIFICATION_MAX_ATTEMPTS,
                    retry_delay_seconds=settings.NOTIFICATION_RETRY_DELAY_SECONDS,
                )
            if processed:
                logger.info("Processed %d pending notifications", processed)
        except Exception:
            logger.exception("Notification worker iteration failed")
        await asyncio.sleep(settings.NOTIFICATION_WORKER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application startup / shutdown lifecycle hook."""
    setup_logging()
    logger.info("Starting %s", settings.APP_NAME)
    # Wait for the database before creating tables.
    await wait_for_db()
    # Create tables (dev convenience — use Alembic in production).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    worker_task: asyncio.Task[None] | None = None
    if settings.NOTIFICATION_WORKER_ENABLED:
        worker_task = asyncio.create_task(_notification_worker_loop())
        logger.info("Notification worker started")
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                logger.info("Notification worker stopped")
        await engine.dispose()
        logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(CorrelationIdMiddleware)

# ── Routers ──────────────────────────────────────────
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(notifications_router)
