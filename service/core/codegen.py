"""Short-code generation.

Codes are random base62 strings rather than a hash of the URL: hashing would give every
user the same code for the same URL (leaking that someone else shortened it) and would
make per-link expiry and deletion collide. Collisions are handled by the caller retrying
a bounded number of times.
"""

import secrets
import string

ALPHABET = string.digits + string.ascii_letters  # base62


def generate_code(length: int = 7) -> str:
    """Return a cryptographically random base62 code of ``length`` characters."""
    if length < 4:
        raise ValueError("code length must be at least 4")
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
