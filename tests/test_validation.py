import pytest
from app.models import CertificateStatus, JobStatus


def test_request_validation_empty_recipients(client):
    """Empty recipients list must reject the whole request with HTTP 422."""
    payload = {
        "course_name": "Python 101",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [],
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422
    assert "recipients" in response.json()["detail"].lower()


def test_request_validation_missing_course_name(client):
    """Missing or whitespace-only course_name must reject with HTTP 422."""
    payload = {
        "course_name": "   ",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [{"name": "Asha", "email": "asha@example.com"}],
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422
    assert "course_name" in response.json()["detail"].lower()


def test_request_validation_invalid_date(client):
    """Invalid date format must reject with HTTP 422."""
    payload = {
        "course_name": "Python 101",
        "organization_name": "Aereo Academy",
        "issue_date": "not-a-real-date",
        "recipients": [{"name": "Asha", "email": "asha@example.com"}],
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_request_validation_exceeding_max_recipients(client, monkeypatch):
    """Recipients list exceeding MAX_RECIPIENTS must reject with HTTP 422."""
    # Temporarily set max_recipients to 5 for test
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_recipients", 5)

    payload = {
        "course_name": "Python 101",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": f"User {i}", "email": f"user{i}@example.com"}
            for i in range(6)
        ],
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422
    assert "exceed" in response.json()["detail"].lower()


def test_recipient_validation_isolation(client):
    """
    Invalid recipient data must NOT reject the whole request (Rule 1).
    Valid recipients must succeed, while invalid ones are marked FAILED with specific reasons.
    """
    payload = {
        "course_name": "Data Science",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "Valid First", "email": "valid1@example.com"},
            {"name": "", "email": "empty_name@example.com"},  # Empty name
            {"name": "Bad Email User", "email": "not-an-email"},  # Bad email
            {"name": "A" * 105, "email": "toolong@example.com"},  # Name too long
            {"name": "Duplicate User", "email": "VALID1@example.com"},  # Duplicate normalized email
            {"name": "Valid Second", "email": "valid2@example.com"},
        ],
    }

    # Must accept the bulk request with 202
    res = client.post("/api/v1/jobs", json=payload)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Check job status
    status_res = client.get(f"/api/v1/jobs/{job_id}")
    assert status_res.status_code == 200
    data = status_res.json()

    assert data["total_count"] == 6
    assert data["success_count"] == 2
    assert data["failed_count"] == 4
    assert data["status"] == JobStatus.COMPLETED_WITH_ERRORS.value

    # Check recipient-specific error messages and positions
    items = data["recipients"]
    assert items[0]["recipient_name"] == "Valid First"
    assert items[0]["status"] == CertificateStatus.SUCCESS.value

    assert items[1]["recipient_name"] == ""
    assert items[1]["status"] == CertificateStatus.FAILED.value
    assert "empty" in items[1]["error_message"].lower()

    assert items[2]["recipient_name"] == "Bad Email User"
    assert items[2]["status"] == CertificateStatus.FAILED.value
    assert "invalid email" in items[2]["error_message"].lower()

    assert items[3]["status"] == CertificateStatus.FAILED.value
    assert "maximum" in items[3]["error_message"].lower()

    assert items[4]["recipient_name"] == "Duplicate User"
    assert items[4]["status"] == CertificateStatus.FAILED.value
    assert "duplicate email" in items[4]["error_message"].lower()

    assert items[5]["recipient_name"] == "Valid Second"
    assert items[5]["status"] == CertificateStatus.SUCCESS.value


def test_duplicate_emails_first_wins(client):
    """
    Verifies that when duplicate emails are supplied, the first occurrence wins (SUCCESS)
    and subsequent occurrences fail with an informative message.
    """
    payload = {
        "course_name": "Deduplication Testing",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "Alice Primary", "email": "alice@example.com"},
            {"name": "Alice Duplicate", "email": "ALICE@EXAMPLE.COM"},
        ],
    }

    res = client.post("/api/v1/jobs", json=payload)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    status_res = client.get(f"/api/v1/jobs/{job_id}")
    items = status_res.json()["recipients"]

    assert items[0]["position"] == 0
    assert items[0]["recipient_name"] == "Alice Primary"
    assert items[0]["status"] == CertificateStatus.SUCCESS.value

    assert items[1]["position"] == 1
    assert items[1]["recipient_name"] == "Alice Duplicate"
    assert items[1]["status"] == CertificateStatus.FAILED.value
    assert "duplicate email" in items[1]["error_message"].lower()


def test_resolve_path_traversal_rejection(test_env):
    """
    Verifies that StorageService strictly rejects relative path traversal attempts.
    """
    storage = test_env["storage"]

    with pytest.raises(ValueError, match="escapes storage directory"):
        storage.resolve_path("../../etc/passwd")

    with pytest.raises(ValueError, match="escapes storage directory"):
        storage.resolve_path("..\\app.db")

