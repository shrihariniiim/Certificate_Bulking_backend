import pytest
from app.models import CertificateStatus, Job, JobStatus
from app.services import job_service


def test_generator_failure_isolation(client, monkeypatch):
    """
    Simulates a rendering/generation error for one recipient by monkeypatching
    generate_certificate_pdf.
    Verifies that:
    1. The failing recipient is marked FAILED with the error recorded.
    2. Other valid recipients succeed normally.
    3. The overall job ends as COMPLETED_WITH_ERRORS.
    """
    real_generator = job_service.generate_certificate_pdf

    def faulty_generator(*args, **kwargs):
        # Fail specifically when rendering "Crash Me"
        recipient_name = kwargs.get("recipient_name") or args[0]
        if recipient_name == "Crash Me":
            raise RuntimeError("Simulated PDF font engine crash")
        return real_generator(*args, **kwargs)

    monkeypatch.setattr(job_service, "generate_certificate_pdf", faulty_generator)

    payload = {
        "course_name": "Failure Resilience Testing",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "Good Recipient 1", "email": "good1@example.com"},
            {"name": "Crash Me", "email": "crash@example.com"},
            {"name": "Good Recipient 2", "email": "good2@example.com"},
        ],
    }

    res = client.post("/api/v1/jobs", json=payload)
    job_id = res.json()["job_id"]

    status_res = client.get(f"/api/v1/jobs/{job_id}")
    data = status_res.json()

    assert data["status"] == JobStatus.COMPLETED_WITH_ERRORS.value
    assert data["total_count"] == 3
    assert data["success_count"] == 2
    assert data["failed_count"] == 1

    items = data["recipients"]
    assert items[0]["recipient_name"] == "Good Recipient 1"
    assert items[0]["status"] == CertificateStatus.SUCCESS.value

    assert items[1]["recipient_name"] == "Crash Me"
    assert items[1]["status"] == CertificateStatus.FAILED.value
    assert "Simulated PDF font engine crash" in items[1]["error_message"]

    assert items[2]["recipient_name"] == "Good Recipient 2"
    assert items[2]["status"] == CertificateStatus.SUCCESS.value


def test_recover_stale_jobs_on_crash(test_env):
    """
    Verifies that any job left in PROCESSING state (e.g. from a server restart)
    is cleanly transitioned to FAILED by recover_stale_jobs().
    """
    session_factory = test_env["session_factory"]
    db = session_factory()

    from datetime import date
    stale_job = Job(
        course_name="Abandoned Job",
        organization_name="Aereo Academy",
        issue_date=date(2026, 10, 8),
        status=JobStatus.PROCESSING.value,
        total_count=1,
    )
    db.add(stale_job)
    db.commit()
    stale_id = stale_job.id
    db.close()

    # Run recovery
    count = job_service.recover_stale_jobs(session_factory=session_factory)
    assert count == 1

    # Verify updated status
    db2 = session_factory()
    recovered = db2.get(Job, stale_id)
    assert recovered.status == JobStatus.FAILED.value
    assert recovered.completed_at is not None
    db2.close()
