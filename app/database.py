from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import get_settings

# Retrieve application settings
settings = get_settings()

# Ensure parent directory exists for SQLite database file
if settings.database_url.startswith("sqlite:///"):
    sqlite_path = settings.database_url.replace("sqlite:///", "")
    if sqlite_path and not sqlite_path.startswith(":memory:"):
        settings.resolved_storage_path

# SQLite requires check_same_thread=False when background threads/tasks access the same connection pool.
# For PostgreSQL/MySQL, connect_args is empty because standard client connections are thread-safe.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

# SQLAlchemy 2.0 Engine
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
    future=True,
)

# Plain sessionmaker (standard SQLAlchemy 2.0 pattern, no scoped_session)
# expire_on_commit=False prevents DetachedInstanceErrors when reading model fields after commit
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# Declarative base class for all ORM models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a dedicated database session per HTTP request.
    Closes the session cleanly upon request completion.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory() -> sessionmaker:
    """
    FastAPI dependency yielding the sessionmaker factory.
    Allows passing the sessionmaker into background workers without coupling
    to a module-level global, making testing cleanly mockable via dependency_overrides.
    """
    return SessionLocal

