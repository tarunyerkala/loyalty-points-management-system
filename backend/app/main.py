"""
FastAPI application entry point for the Loyalty Points Management System.

Provides:
- Interactive Swagger UI at `/docs` and OpenAPI JSON at `/openapi.json`
- REST API endpoints for customers, accounts, orders, points lifecycle, analytics, and auditing
- Static frontend dashboard served cleanly at `/`
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import FRONTEND_DIR
from app.database import SessionLocal, init_db_schema
from app.routes import analytics, customers, operations
from app.services.tier_manager import ensure_reference_data

logger = logging.getLogger(__name__)

ALLOWED_CORS_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]


class UnhandledExceptionMiddleware:
    """Catch unhandled HTTP exceptions inside CORSMiddleware so error responses keep CORS headers."""

    def __init__(self, asgi_app: ASGIApp) -> None:
        self.app = asgi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def _send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            logger.exception("Unhandled exception on %s %s", scope.get("method"), scope.get("path"))
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error."},
            )
            await response(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize schema and reference tiers/rules/rewards safely on startup."""
    init_db_schema()
    db = SessionLocal()
    try:
        ensure_reference_data(db)
        db.commit()
    finally:
        db.close()
    yield


app = FastAPI(
    title="Loyalty Points Management System API",
    description=(
        "End-to-end Loyalty Points Management & Audit Platform supporting accrual, "
        "atomic redemption, partial/full reversals, FIFO expiration, tier progression, "
        "and independent ledger anomaly detection."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Register UnhandledExceptionMiddleware before CORSMiddleware so CORSMiddleware wraps it
# (Starlette wraps middlewares in reverse registration order) and attaches CORS headers even on 500s.
app.add_middleware(UnhandledExceptionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customers.router)
app.include_router(operations.router)
app.include_router(analytics.router)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
def serve_frontend():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Loyalty Points Management System API is running. Visit /docs for Swagger UI."}


@app.get("/styles.css", include_in_schema=False)
def serve_styles():
    return FileResponse(str(FRONTEND_DIR / "styles.css"), media_type="text/css")


@app.get("/app.js", include_in_schema=False)
def serve_app_js():
    return FileResponse(str(FRONTEND_DIR / "app.js"), media_type="application/javascript")


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "loyalty-points-management-system"}

