import pytest
from pathlib import Path
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db, get_session_factory
from app.main import app
from app.services.storage import StorageService, get_storage


@pytest.fixture
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Sets up a completely isolated testing environment per test:
    - Temporary SQLite file-based database
    - Temporary certificates storage directory
    - Redirects get_db, get_session_factory, and background worker's SessionLocal to test DB
    - Overrides default_storage to point to the temporary storage directory
    """
    # 1. Ephemeral database
    test_db_file = tmp_path / "test.db"
    test_db_url = f"sqlite:///{test_db_file}"
    test_engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=test_engine)

    TestSessionLocal = sessionmaker(
        bind=test_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    # 2. Ephemeral storage
    test_storage_dir = tmp_path / "storage"
    test_storage = StorageService(base_dir=test_storage_dir)

    # 3. Dependency overrides
    def override_get_db() -> Generator[Session, None, None]:
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_session_factory():
        return TestSessionLocal

    def override_get_storage():
        return test_storage

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = override_get_session_factory
    app.dependency_overrides[get_storage] = override_get_storage

    # 4. Monkeypatch module-level SessionLocal and storage references
    monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.services.job_service.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.services.storage.default_storage", test_storage)
    monkeypatch.setattr("app.services.job_service.default_storage", test_storage)

    yield {
        "engine": test_engine,
        "session_factory": TestSessionLocal,
        "storage": test_storage,
        "storage_dir": test_storage_dir,
    }

    # Teardown
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def client(test_env) -> Generator[TestClient, None, None]:
    """TestClient fixture with the test environment active."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(test_env) -> Generator[Session, None, None]:
    """Yields a direct session to the isolated test database for direct model inspection."""
    session = test_env["session_factory"]()
    try:
        yield session
    finally:
        session.close()
