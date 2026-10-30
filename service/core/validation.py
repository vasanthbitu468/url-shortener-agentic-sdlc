"""Input validation for URLs and custom aliases.

Security goals:
- Only http/https targets (no javascript:, data:, file: ...).
- Refuse targets that point at loopback, private, link-local or reserved addresses, so the
  shortener cannot be used to reach internal services or cloud metadata endpoints.
- Refuse links that point back at this service (redirect loops).

Limitation: hostnames are checked literally; DNS is not resolved here, so a public name that
resolves to a private IP is not caught. A production deployment should resolve and re-check,
or enforce this at an egress proxy.
"""

import ipaddress
import re
from urllib.parse import urlsplit

ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
RESERVED_ALIASES = frozenset(
    {"api", "docs", "redoc", "openapi", "health", "ready", "static", "admin"}
)
BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal"})


class ValidationError(ValueError):
    """Raised when user input is rejected. The message is safe to return to clients."""


def validate_target_url(url: str, *, max_length: int, own_host: str | None = None) -> str:
    url = url.strip()
    if not url:
        raise ValidationError("url must not be empty")
    if len(url) > max_length:
        raise ValidationError(f"url must be at most {max_length} characters")

    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValidationError("only http and https urls are allowed")
    if parts.username or parts.password:
        raise ValidationError("urls with embedded credentials are not allowed")

    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValidationError("url must include a host")
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise ValidationError("url host is not allowed")
    if own_host and host == own_host.lower():
        raise ValidationError("url must not point to this service")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise ValidationError("url must not point to a private or reserved address")

    return url


def validate_alias(alias: str) -> str:
    if not ALIAS_RE.fullmatch(alias):
        raise ValidationError("alias must be 3-32 characters: letters, digits, '-' or '_'")
    if alias.lower() in RESERVED_ALIASES:
        raise ValidationError("alias is reserved")
    return alias
