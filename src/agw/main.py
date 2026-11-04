from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from agw.api import (
    agents,
    audit,
    auth,
    identities,
    inventory,
    mcp,
    oidc,
    public,
    services,
    signups,
)
from agw.config import Settings
from agw.core.errors import ApiError
from agw.core.time import utcnow
from agw.db.models import TraceSpan
from agw.store import build_store_provider
from agw.vault.ca import InternalCA

WEB_DIR = Path(__file__).parent / "web"
DIST_DIR = WEB_DIR / "dist"

logger = logging.getLogger(__name__)


def _ui_file(path: str | None = None):
    """Serve the built SPA, falling back to the placeholder before a build."""
    if not DIST_DIR.is_dir():
        return FileResponse(WEB_DIR / "placeholder.html")
    if path:
        candidate = (DIST_DIR / path).resolve()
        if candidate.is_file() and DIST_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
    return FileResponse(DIST_DIR / "index.html")


async def _record_request_span(
    request: Request,
    response,
    trace_id: str,
    started: float,
    started_at,
) -> None:
    """Write the root span for an API request.

    Tracing is best effort: a failure here must never change the response the
    caller already produced.
    """
    path = request.url.path
    if not (path.startswith("/v1/") or path.startswith("/mcp/")):
        return
    workspace_id = getattr(request.state, "workspace_id", None)
    provider = getattr(request.app.state, "store_provider", None)
    if workspace_id is None or provider is None:
        return
    route = request.scope.get("route")
    principal = getattr(request.state, "principal", None)
    span = TraceSpan(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        trace_id=trace_id,
        span_id="root",
        parent_span_id=None,
        name=f"{request.method} {getattr(route, 'path', path)}",
        kind="server",
        status="ok" if response.status_code < 400 else "error",
        duration_ms=int((time.perf_counter() - started) * 1000),
        actor_type=principal.kind if principal is not None else None,
        actor_id=principal.id if principal is not None else None,
        attributes={
            "status_code": response.status_code,
            "method": request.method,
            "path": path,
        },
        started_at=started_at,
        created_at=utcnow(),
    )
    try:
        async with provider.store() as store:
            await store.record_trace_span(span)
            await store.commit()
    except Exception:  # noqa: BLE001 - tracing is not allowed to break requests
        logger.warning("trace span not recorded", exc_info=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        provider = build_store_provider(app_settings)
        app.state.store_provider = provider
        app.state.ca = (
            InternalCA(app_settings.ca_dir, ca_ttl_days=app_settings.ca_cert_ttl_days)
            if app_settings.ca_enabled
            else None
        )
        await provider.startup(create_tables=app_settings.auto_create)
        try:
            yield
        finally:
            await provider.shutdown()

    app = FastAPI(
        title="AI Gateway",
        version="0.1.0",
        description="Identity and policy gateway for AI agents.",
        lifespan=lifespan,
    )
    app.state.settings = app_settings

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.trace_id = trace_id
        started_at = utcnow()
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        # Record the span after the body is sent: the write must never add
        # latency to a response that is already complete.
        existing = response.background

        async def record_after_response() -> None:
            if existing is not None:
                await existing()
            await _record_request_span(request, response, trace_id, started, started_at)

        response.background = BackgroundTask(record_after_response)
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            exc.body(getattr(request.state, "trace_id", None)),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {
                "error": "invalid_request",
                "message": "request validation failed",
                "detail": exc.errors(),
                "trace_id": getattr(request.state, "trace_id", None),
            },
            status_code=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            {
                "error": "http_error",
                "message": str(exc.detail),
                "trace_id": getattr(request.state, "trace_id", None),
            },
            status_code=exc.status_code,
        )

    app.include_router(public.router)
    app.include_router(auth.router)
    app.include_router(oidc.router)
    app.include_router(signups.router)
    app.include_router(identities.router)
    app.include_router(agents.router)
    app.include_router(services.router)
    app.include_router(inventory.router)
    app.include_router(audit.router)
    app.include_router(mcp.router)

    if app_settings.ui_enabled:

        @app.get("/", include_in_schema=False)
        async def ui_index():
            return _ui_file()

        @app.get("/activate", include_in_schema=False)
        async def activate_placeholder():
            return FileResponse(WEB_DIR / "placeholder.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def ui_fallback(full_path: str):
            reserved = (
                "v1/",
                "mcp/",
                "healthz",
                "docs",
                "redoc",
                "openapi.json",
                ".well-known/",
            )
            if full_path.startswith(reserved):
                raise StarletteHTTPException(status_code=404)
            return _ui_file(full_path)

    return app


app = create_app()
