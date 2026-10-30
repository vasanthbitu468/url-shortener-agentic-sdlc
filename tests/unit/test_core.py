import pytest

from service.core.cache import TTLCache
from service.core.codegen import ALPHABET, generate_code
from service.core.ratelimit import RateLimiter
from service.core.validation import ValidationError, validate_alias, validate_target_url


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# ---- codegen ------------------------------------------------------------------------------


def test_generate_code_length_and_alphabet():
    code = generate_code(7)
    assert len(code) == 7
    assert set(code) <= set(ALPHABET)


def test_generate_code_is_random():
    assert len({generate_code(7) for _ in range(500)}) == 500


def test_generate_code_rejects_short_length():
    with pytest.raises(ValueError):
        generate_code(3)


# ---- url validation -----------------------------------------------------------------------

V = dict(max_length=2048)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/a?b=c#d",
        "https://8.8.8.8/path",
        "https://sub.example.co.uk",
    ],
)
def test_valid_urls(url):
    assert validate_target_url(url, **V) == url


@pytest.mark.parametrize(
    "url, reason",
    [
        ("", "empty"),
        ("ftp://example.com", "http and https"),
        ("javascript:alert(1)", "http and https"),
        ("https://", "host"),
        ("https://user:pw@example.com", "credentials"),
        ("http://localhost:8080", "not allowed"),
        ("http://api.localhost", "not allowed"),
        ("http://127.0.0.1", "private"),
        ("http://10.0.0.5", "private"),
        ("http://192.168.1.1", "private"),
        ("http://169.254.169.254/latest/meta-data", "private"),
        ("http://[::1]/", "private"),
        ("http://0.0.0.0", "private"),
    ],
)
def test_invalid_urls(url, reason):
    with pytest.raises(ValidationError, match=reason):
        validate_target_url(url, **V)


def test_url_too_long():
    with pytest.raises(ValidationError, match="at most"):
        validate_target_url("https://example.com/" + "a" * 3000, **V)


def test_url_pointing_at_own_host_rejected():
    with pytest.raises(ValidationError, match="this service"):
        validate_target_url("https://sho.rt/abc", max_length=2048, own_host="sho.rt")


# ---- alias validation ---------------------------------------------------------------------


@pytest.mark.parametrize("alias", ["abc", "my-link", "My_Link_2026", "a" * 32])
def test_valid_aliases(alias):
    assert validate_alias(alias) == alias


@pytest.mark.parametrize("alias", ["ab", "a" * 33, "has space", "slash/no", "dot.no", "ümlaut"])
def test_invalid_aliases(alias):
    with pytest.raises(ValidationError):
        validate_alias(alias)


@pytest.mark.parametrize("alias", ["api", "Health", "DOCS"])
def test_reserved_aliases(alias):
    with pytest.raises(ValidationError, match="reserved"):
        validate_alias(alias)


# ---- rate limiter -------------------------------------------------------------------------


def test_rate_limiter_blocks_after_limit_and_resets():
    clock = FakeClock(0)
    rl = RateLimiter(3, 60, clock=clock)
    assert [rl.allow("ip") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("other") is True  # keys are independent
    clock.t = 61
    assert rl.allow("ip") is True


def test_rate_limiter_retry_after():
    clock = FakeClock(50)
    rl = RateLimiter(1, 60, clock=clock)
    assert rl.retry_after() == 10


def test_rate_limiter_rejects_bad_config():
    with pytest.raises(ValueError):
        RateLimiter(0, 60)


def test_rate_limiter_evicts_stale_windows():
    clock = FakeClock(0)
    rl = RateLimiter(5, 1, clock=clock)
    for i in range(50_001):
        rl.allow(f"k{i}")
    clock.t = 5
    rl.allow("fresh")
    assert list(rl._windows) == ["fresh"]


# ---- cache --------------------------------------------------------------------------------


def test_cache_ttl_expiry():
    clock = FakeClock(0)
    c: TTLCache[str] = TTLCache(10, 5, clock=clock)
    c.set("a", "1")
    assert c.get("a") == "1"
    clock.t = 6
    assert c.get("a") is None


def test_cache_lru_eviction_and_invalidate():
    c: TTLCache[int] = TTLCache(2, 100)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")  # a is now most recent
    c.set("c", 3)  # evicts b
    assert c.get("b") is None
    assert c.get("a") == 1
    c.invalidate("a")
    assert c.get("a") is None
    c.clear()
    assert c.get("c") is None
