"""Engine and session factory."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from service.db.models import Base


def build_engine(database_url: str) -> Engine:
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url or database_url == "sqlite://":
            kwargs["poolclass"] = StaticPool  # one shared in-memory DB across threads
    return create_engine(database_url, future=True, **kwargs)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create tables. Schema changes after v1 go through migrations, not this call."""
    Base.metadata.create_all(engine)
