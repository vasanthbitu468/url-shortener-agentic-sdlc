import os

# Point the module-level app at an in-memory DB before anything imports service.main.
os.environ.setdefault("APP_DATABASE_URL", "sqlite://")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from service.config import Settings  # noqa: E402
from service.main import create_app  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        base_url="http://sho.rt",
        rate_limit_requests=1000,
        rate_limit_window_seconds=60,
    )


@pytest.fixture
def app(settings):
    application = create_app(settings)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def session(app):
    s = app.state.session_factory()
    yield s
    s.close()
