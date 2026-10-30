"""HTTP routes. Thin layer: validate input, call LinkService, map errors to status codes."""

from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from service.api.schemas import (
    CreateUrlRequest,
    ErrorResponse,
    HealthResponse,
    StatsResponse,
    UrlResponse,
)
from service.core.links import (
    AliasTakenError,
    CodeSpaceExhaustedError,
    IdempotencyConflictError,
    LinkGoneError,
    LinkNotFoundError,
    LinkService,
    as_utc,
)
from service.core.validation import ValidationError
from service.db.models import Url

api = APIRouter(prefix="/api/v1", tags=["urls"])
ops = APIRouter(tags=["ops"])
redirect = APIRouter(tags=["redirect"])


# ---- dependencies ---------------------------------------------------------------------------


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_link_service(request: Request, session: Session = Depends(get_session)) -> LinkService:
    s = request.app.state.settings
    return LinkService(
        session,
        code_length=s.code_length,
        code_max_attempts=s.code_max_attempts,
        max_url_length=s.max_url_length,
        own_host=urlsplit(s.base_url).hostname,
    )


def enforce_rate_limit(request: Request, response: Response) -> None:
    limiter = request.app.state.rate_limiter
    client = request.client.host if request.client else "unknown"
    if not limiter.allow(client):
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(limiter.retry_after())},
        )


def to_response(url: Url, base_url: str) -> UrlResponse:
    return UrlResponse(
        code=url.code,
        short_url=f"{base_url.rstrip('/')}/{url.code}",
        long_url=url.long_url,
        created_at=as_utc(url.created_at),
        expires_at=as_utc(url.expires_at),
        is_custom=url.is_custom,
    )


NOT_FOUND = {404: {"model": ErrorResponse, "description": "Link not found"}}
GONE = {410: {"model": ErrorResponse, "description": "Link expired or deleted"}}


# ---- API ------------------------------------------------------------------------------------


@api.post(
    "/urls",
    response_model=UrlResponse,
    status_code=201,
    responses={
        200: {"model": UrlResponse, "description": "Replayed via Idempotency-Key"},
        409: {"model": ErrorResponse, "description": "Alias taken or idempotency conflict"},
        422: {"model": ErrorResponse, "description": "Invalid input"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
    dependencies=[Depends(enforce_rate_limit)],
)
def create_url(
    body: CreateUrlRequest,
    request: Request,
    response: Response,
    service: LinkService = Depends(get_link_service),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=128),
) -> UrlResponse:
    try:
        result = service.create(
            body.url,
            custom_alias=body.custom_alias,
            expires_at=body.expires_at,
            idempotency_key=idempotency_key,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (AliasTakenError, IdempotencyConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CodeSpaceExhaustedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.created:
        response.status_code = 200
    return to_response(result.url, request.app.state.settings.base_url)


@api.get("/urls/{code}", response_model=UrlResponse, responses={**NOT_FOUND, **GONE})
def get_url(
    code: str, request: Request, service: LinkService = Depends(get_link_service)
) -> UrlResponse:
    try:
        url = service.get(code)
    except LinkNotFoundError as exc:
        raise HTTPException(status_code=404, detail="link not found") from exc
    except LinkGoneError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    return to_response(url, request.app.state.settings.base_url)


@api.get("/urls/{code}/stats", response_model=StatsResponse, responses=NOT_FOUND)
def get_stats(code: str, service: LinkService = Depends(get_link_service)) -> StatsResponse:
    try:
        return StatsResponse(**service.stats(code))
    except LinkNotFoundError as exc:
        raise HTTPException(status_code=404, detail="link not found") from exc


@api.delete("/urls/{code}", status_code=204, responses={**NOT_FOUND, **GONE})
def delete_url(
    code: str, request: Request, service: LinkService = Depends(get_link_service)
) -> Response:
    try:
        service.delete(code)
    except LinkNotFoundError as exc:
        raise HTTPException(status_code=404, detail="link not found") from exc
    except LinkGoneError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    request.app.state.cache.invalidate(code)
    return Response(status_code=204)


# ---- ops ------------------------------------------------------------------------------------


@ops.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@ops.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse, "description": "Database unavailable"}},
)
def ready(session: Session = Depends(get_session)) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any DB failure means not ready
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return HealthResponse(status="ready")


# ---- redirect (registered last so it never shadows other routes) ----------------------------


def _record_click(app, code: str, referrer: str | None, user_agent: str | None) -> None:
    session = app.state.session_factory()
    try:
        s = app.state.settings
        LinkService(
            session,
            code_length=s.code_length,
            code_max_attempts=s.code_max_attempts,
            max_url_length=s.max_url_length,
        ).record_click(code, referrer=referrer, user_agent=user_agent)
    finally:
        session.close()


@redirect.get(
    "/{code}",
    status_code=302,
    responses={302: {"description": "Redirect to the target URL"}, **NOT_FOUND, **GONE},
)
def follow(
    code: str,
    request: Request,
    background: BackgroundTasks,
    service: LinkService = Depends(get_link_service),
) -> RedirectResponse:
    cache = request.app.state.cache
    cached = cache.get(code)
    if cached is not None:
        long_url, expires_at = cached
        if expires_at is not None and expires_at <= datetime.now(UTC):
            cache.invalidate(code)
            raise HTTPException(status_code=410, detail="link has expired")
    else:
        try:
            url = service.get(code)
        except LinkNotFoundError as exc:
            raise HTTPException(status_code=404, detail="link not found") from exc
        except LinkGoneError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        long_url = url.long_url
        cache.set(code, (long_url, as_utc(url.expires_at)))

    background.add_task(
        _record_click,
        request.app,
        code,
        request.headers.get("referer"),
        request.headers.get("user-agent"),
    )
    return RedirectResponse(long_url, status_code=302, headers={"Cache-Control": "no-store"})
