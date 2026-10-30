from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from service.config import Settings
from service.core.links import LinkService
from service.db.models import Url
from service.main import create_app

TARGET = "https://example.com/some/long/path?x=1"


def create(client, **body):
    return client.post("/api/v1/urls", json={"url": TARGET, **body})


# ---- create -------------------------------------------------------------------------------


def test_create_returns_short_url(client):
    r = create(client)
    assert r.status_code == 201
    data = r.json()
    assert data["long_url"] == TARGET
    assert len(data["code"]) == 7
    assert data["short_url"] == f"http://sho.rt/{data['code']}"
    assert data["is_custom"] is False
    assert data["expires_at"] is None


def test_same_url_twice_gets_different_codes(client):
    assert create(client).json()["code"] != create(client).json()["code"]


def test_create_with_custom_alias(client):
    r = create(client, custom_alias="my-link")
    assert r.status_code == 201
    assert r.json()["code"] == "my-link"
    assert r.json()["is_custom"] is True


def test_duplicate_alias_conflicts(client):
    create(client, custom_alias="taken")
    r = create(client, custom_alias="taken")
    assert r.status_code == 409
    assert "already in use" in r.json()["detail"]


def test_invalid_url_rejected(client):
    r = client.post("/api/v1/urls", json={"url": "http://169.254.169.254/"})
    assert r.status_code == 422
    assert "private" in r.json()["detail"]


def test_reserved_alias_rejected(client):
    assert create(client, custom_alias="health").status_code == 422


def test_unknown_field_rejected(client):
    assert client.post("/api/v1/urls", json={"url": TARGET, "evil": 1}).status_code == 422


def test_expiry_in_past_rejected(client):
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    r = create(client, expires_at=past)
    assert r.status_code == 422
    assert "future" in r.json()["detail"]


def test_naive_expiry_treated_as_utc(client):
    future = (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None).isoformat()
    r = create(client, expires_at=future)
    assert r.status_code == 201
    assert r.json()["expires_at"] is not None


# ---- idempotency --------------------------------------------------------------------------


def test_idempotency_key_replays_same_link(client):
    h = {"Idempotency-Key": "abc-123"}
    first = client.post("/api/v1/urls", json={"url": TARGET}, headers=h)
    second = client.post("/api/v1/urls", json={"url": TARGET}, headers=h)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["code"] == second.json()["code"]


def test_idempotency_key_reuse_with_different_body_conflicts(client):
    h = {"Idempotency-Key": "abc-456"}
    client.post("/api/v1/urls", json={"url": TARGET}, headers=h)
    r = client.post("/api/v1/urls", json={"url": "https://other.example.com"}, headers=h)
    assert r.status_code == 409


# ---- redirect + analytics -----------------------------------------------------------------


def test_redirect_and_stats(client):
    code = create(client).json()["code"]
    for _ in range(3):
        r = client.get(
            f"/{code}", headers={"Referer": "https://ref.example", "User-Agent": "pytest"}
        )
        assert r.status_code == 302
        assert r.headers["location"] == TARGET
        assert r.headers["cache-control"] == "no-store"

    stats = client.get(f"/api/v1/urls/{code}/stats").json()
    assert stats["total_clicks"] == 3
    assert stats["last_accessed_at"] is not None
    assert sum(d["clicks"] for d in stats["clicks_by_day"]) == 3


def test_click_event_stores_no_raw_user_agent(client, session):
    from service.db.models import ClickEvent

    code = create(client).json()["code"]
    client.get(f"/{code}", headers={"User-Agent": "SecretBrowser/1.0"})
    ev = session.query(ClickEvent).filter_by(code=code).one()
    assert ev.user_agent_hash and "SecretBrowser" not in ev.user_agent_hash
    assert len(ev.user_agent_hash) == 64


def test_redirect_unknown_code_404(client):
    assert client.get("/nope123").status_code == 404


def test_expired_link_returns_410(client, session):
    code = create(client).json()["code"]
    url = session.query(Url).filter_by(code=code).one()
    url.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert client.get(f"/{code}").status_code == 410
    assert client.get(f"/api/v1/urls/{code}").status_code == 410


def test_cached_link_expiry_still_enforced(client, app):
    code = create(client).json()["code"]
    client.get(f"/{code}")  # warms cache
    app.state.cache.set(code, (TARGET, datetime.now(UTC) - timedelta(seconds=1)))
    assert client.get(f"/{code}").status_code == 410


# ---- metadata + delete --------------------------------------------------------------------


def test_get_metadata(client):
    code = create(client).json()["code"]
    r = client.get(f"/api/v1/urls/{code}")
    assert r.status_code == 200
    assert r.json()["long_url"] == TARGET


def test_get_metadata_unknown(client):
    assert client.get("/api/v1/urls/unknown").status_code == 404
    assert client.get("/api/v1/urls/unknown/stats").status_code == 404


def test_delete_is_soft_and_invalidates_cache(client):
    code = create(client).json()["code"]
    client.get(f"/{code}")  # cache it
    assert client.delete(f"/api/v1/urls/{code}").status_code == 204
    assert client.get(f"/{code}").status_code == 410
    assert client.delete(f"/api/v1/urls/{code}").status_code == 410
    # stats remain available after deletion (audit)
    assert client.get(f"/api/v1/urls/{code}/stats").status_code == 200


def test_delete_unknown(client):
    assert client.delete("/api/v1/urls/unknown").status_code == 404


# ---- ops ----------------------------------------------------------------------------------


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_ready_reports_db_failure(app, client):
    class BrokenSession:
        def execute(self, *_a, **_k):
            raise RuntimeError("db down")

        def close(self):
            pass

    app.state.session_factory = BrokenSession
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["detail"] == "database unavailable"


def test_request_id_header(client):
    r = client.get("/health", headers={"X-Request-ID": "req-1"})
    assert r.headers["x-request-id"] == "req-1"
    assert client.get("/health").headers["x-request-id"]


def test_openapi_contract_lists_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/urls", "/api/v1/urls/{code}", "/api/v1/urls/{code}/stats", "/{code}"} <= set(
        paths
    )


# ---- rate limiting + collisions -----------------------------------------------------------


def test_rate_limit_on_create():
    app = create_app(Settings(database_url="sqlite://", rate_limit_requests=2))
    c = TestClient(app)
    assert create(c).status_code == 201
    assert create(c).status_code == 201
    r = create(c)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    app.state.engine.dispose()


def test_record_click_for_unknown_code_is_noop(session):
    svc = LinkService(session, code_length=7, code_max_attempts=3, max_url_length=2048)
    svc.record_click("missing", referrer=None, user_agent=None)  # must not raise


def test_code_collision_retries_then_gives_up(app, session, monkeypatch):
    import service.core.links as links

    svc = LinkService(session, code_length=7, code_max_attempts=3, max_url_length=2048)
    session.add(Url(code="AAAAAAA", long_url=TARGET))
    session.commit()

    monkeypatch.setattr(links, "generate_code", lambda n: "AAAAAAA")
    client = TestClient(app)
    r = client.post("/api/v1/urls", json={"url": TARGET})
    assert r.status_code == 503

    seq = iter(["AAAAAAA", "BBBBBBB"])
    monkeypatch.setattr(links, "generate_code", lambda n: next(seq))
    assert svc.create(TARGET).url.code == "BBBBBBB"
