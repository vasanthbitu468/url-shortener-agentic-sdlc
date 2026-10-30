"""Link business logic, independent of HTTP.

The API layer translates the exceptions here into status codes.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from service.core.codegen import generate_code
from service.core.validation import ValidationError, validate_alias, validate_target_url
from service.db.models import ClickEvent, IdempotencyKey, Url


class LinkError(Exception):
    """Base class for domain errors."""


class AliasTakenError(LinkError):
    pass


class LinkNotFoundError(LinkError):
    pass


class LinkGoneError(LinkError):
    """The link existed but has expired or been deleted."""


class IdempotencyConflictError(LinkError):
    """The idempotency key was reused with a different request body."""


class CodeSpaceExhaustedError(LinkError):
    pass


@dataclass(frozen=True)
class CreateResult:
    url: Url
    created: bool  # False when replayed from an idempotency key


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat stored naive datetimes as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


class LinkService:
    def __init__(
        self,
        session: Session,
        *,
        code_length: int,
        code_max_attempts: int,
        max_url_length: int,
        own_host: str | None = None,
        ua_salt: str = "url-shortener",
    ) -> None:
        self.session = session
        self.code_length = code_length
        self.code_max_attempts = code_max_attempts
        self.max_url_length = max_url_length
        self.own_host = own_host
        self._ua_salt = ua_salt.encode()

    # ---- create -------------------------------------------------------------------------

    def create(
        self,
        long_url: str,
        *,
        custom_alias: str | None = None,
        expires_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> CreateResult:
        long_url = validate_target_url(
            long_url, max_length=self.max_url_length, own_host=self.own_host
        )
        if custom_alias is not None:
            custom_alias = validate_alias(custom_alias)
        if expires_at is not None:
            expires_at = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
            if expires_at <= _now():
                raise ValidationError("expires_at must be in the future")

        request_hash = None
        if idempotency_key:
            payload = json.dumps(
                {
                    "url": long_url,
                    "alias": custom_alias,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                sort_keys=True,
            )
            request_hash = hashlib.sha256(payload.encode()).hexdigest()
            existing = self.session.get(IdempotencyKey, idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        "idempotency key was already used with a different request"
                    )
                url = self._get_by_code(existing.code)
                if url is not None:
                    return CreateResult(url=url, created=False)

        url = self._insert(long_url, custom_alias, expires_at)

        if idempotency_key and request_hash:
            self.session.add(
                IdempotencyKey(key=idempotency_key, request_hash=request_hash, code=url.code)
            )
            self.session.commit()
        return CreateResult(url=url, created=True)

    def _insert(self, long_url: str, alias: str | None, expires_at: datetime | None) -> Url:
        if alias is not None:
            url = Url(code=alias, long_url=long_url, is_custom=True, expires_at=expires_at)
            self.session.add(url)
            try:
                self.session.commit()
            except IntegrityError as exc:
                self.session.rollback()
                raise AliasTakenError("alias is already in use") from exc
            return url

        for _ in range(self.code_max_attempts):
            url = Url(
                code=generate_code(self.code_length), long_url=long_url, expires_at=expires_at
            )
            self.session.add(url)
            try:
                self.session.commit()
                return url
            except IntegrityError:
                self.session.rollback()  # collision: retry with a new code
        raise CodeSpaceExhaustedError("could not allocate a unique code; try again")

    # ---- read ---------------------------------------------------------------------------

    def _get_by_code(self, code: str) -> Url | None:
        return self.session.scalar(select(Url).where(Url.code == code))

    def get(self, code: str, *, include_inactive: bool = False) -> Url:
        url = self._get_by_code(code)
        if url is None:
            raise LinkNotFoundError(code)
        if not include_inactive:
            self.ensure_active(url)
        return url

    @staticmethod
    def ensure_active(url: Url) -> None:
        if url.is_deleted:
            raise LinkGoneError("link has been deleted")
        expires_at = as_utc(url.expires_at)
        if expires_at is not None and expires_at <= _now():
            raise LinkGoneError("link has expired")

    def stats(self, code: str) -> dict:
        url = self.get(code, include_inactive=True)
        day = func.date(ClickEvent.ts)
        rows = self.session.execute(
            select(day.label("day"), func.count().label("clicks"))
            .where(ClickEvent.code == code)
            .group_by(day)
            .order_by(day)
        ).all()
        return {
            "code": url.code,
            "total_clicks": url.click_count,
            "last_accessed_at": as_utc(url.last_accessed_at),
            "clicks_by_day": [{"day": str(r.day), "clicks": r.clicks} for r in rows],
        }

    # ---- write --------------------------------------------------------------------------

    def delete(self, code: str) -> Url:
        url = self.get(code, include_inactive=True)
        if url.is_deleted:
            raise LinkGoneError("link has already been deleted")
        url.is_deleted = True
        self.session.commit()
        return url

    def record_click(self, code: str, *, referrer: str | None, user_agent: str | None) -> None:
        ua_hash = (
            hmac.new(self._ua_salt, user_agent.encode(), hashlib.sha256).hexdigest()
            if user_agent
            else None
        )
        # Atomic increment in SQL so concurrent redirects don't lose counts.
        result = self.session.execute(
            update(Url)
            .where(Url.code == code)
            .values(click_count=Url.click_count + 1, last_accessed_at=_now())
        )
        if result.rowcount == 0:
            self.session.rollback()
            return
        self.session.add(
            ClickEvent(
                code=code, referrer=referrer[:512] if referrer else None, user_agent_hash=ua_hash
            )
        )
        self.session.commit()
