"""App factory: every service gets the same health, metrics, logging and request-id
behaviour so the platform (Kubernetes probes, Prometheus) treats them uniformly."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import db
from .config import get_settings
from .logging_setup import request_id_var, setup_logging
from .metrics import PrometheusMiddleware

log = logging.getLogger(__name__)


def create_app(
    service: str,
    routers: Iterable[APIRouter],
    on_startup: Callable[[], None] | None = None,
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        setup_logging(service, settings.log_level)
        db.init_schema()
        if on_startup:
            on_startup()
        log.info("%s started (env=%s)", service, settings.app_env)
        yield
        log.info("%s shutting down", service)

    app = FastAPI(
        title=f"shop-{service}",
        lifespan=lifespan,
        # Hide interactive docs in production.
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(PrometheusMiddleware, service=service)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        if db.ping():
            return {"status": "ready"}
        return JSONResponse({"status": "db unavailable"}, status_code=503)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    for router in routers:
        app.include_router(router)
    return app
