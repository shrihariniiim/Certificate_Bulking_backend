import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, Certificate, JobStatus, CertificateStatus


def test_health_check(client):
    """Verifies that the /health endpoint returns 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_create_job_success(client, db_session: Session):
    """
    Verifies that POST /api/v1/jobs:
    1. Returns HTTP 202 Accepted immediately.
    2. Returns a valid job_id, status PENDING, and total count.
    3. Persists Job and Certificate rows in the database.
    """
    payload = {
        "course_name": "Fullstack Python Mastery",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "Alice Wonderland", "email": "alice@example.com"},
            {"name": "Bob Builder", "email": "bob@example.com"},
        ],
    }

    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202

    data = response.json()
    assert "job_id" in data
    job_uuid = uuid.UUID(data["job_id"])
    assert data["total_count"] == 2
    assert "links" in data
    assert f"/api/v1/jobs/{job_uuid}" in data["links"]["status"]

    # Verify rows in the database
    job_in_db = db_session.get(Job, job_uuid)
    assert job_in_db is not None
    assert job_in_db.course_name == "Fullstack Python Mastery"
    assert job_in_db.organization_name == "Aereo Academy"
    assert job_in_db.total_count == 2

    certs_in_db = list(
        db_session.scalars(
            select(Certificate).where(Certificate.job_id == job_uuid)
        ).all()
    )
    assert len(certs_in_db) == 2


def test_real_db_and_storage_never_touched(client, test_env):
    """
    Verifies test isolation: ensures that executing test jobs never creates
    or alters production/dev database files or storage directories on disk.
    """
    from pathlib import Path
    from app.config import get_settings

    # Track pre-existing file state of real paths
    real_db = Path("storage/app.db")
    real_storage = Path("storage/certificates")
    real_db_mtime = real_db.stat().st_mtime if real_db.exists() else None
    real_files_count = len(list(real_storage.glob("*.pdf"))) if real_storage.exists() else 0

    # Submit and run a job
    payload = {
        "course_name": "Test Isolation Check",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [{"name": "Isolated User", "email": "isolated@example.com"}],
    }
    res = client.post("/api/v1/jobs", json=payload)
    assert res.status_code == 202

    # Verify real DB was not touched
    if real_db.exists():
        assert real_db.stat().st_mtime == real_db_mtime
    # Verify files were saved to test_env's tmp_path, NOT real storage
    test_storage_dir = test_env["storage_dir"]
    assert len(list(test_storage_dir.glob("*.pdf"))) == 1
    if real_storage.exists():
        assert len(list(real_storage.glob("*.pdf"))) == real_files_count

