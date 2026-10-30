"""Application factory and entry point.

Run locally:  uvicorn service.main:app --reload
"""

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request

from service.api.routes import api, ops, redirect
from service.config import Settings, get_settings
from service.core.cache import TTLCache
from service.core.ratelimit import RateLimiter
from service.db.session import build_engine, build_session_factory, init_db

logger = logging.getLogger("service")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        payload.update(getattr(record, "extra_fields", {}))
        return json.dumps(payload)


def _configure_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging()

    app = FastAPI(
        title="URL Shortener",
        version="1.0.0",
        description="Create short links, follow them, and read click analytics.",
    )

    engine = build_engine(settings.database_url)
    init_db(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.rate_limiter = RateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )
    app.state.cache = TTLCache(settings.cache_max_entries, settings.cache_ttl_seconds)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                }
            },
        )
        return response

    app.include_router(ops)
    app.include_router(api)
    app.include_router(redirect)  # last: catch-all /{code}
    return app


app = create_app()
