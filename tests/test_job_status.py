from app.models import JobStatus, CertificateStatus


def test_job_status_all_success(client):
    """Job with 100% valid recipients should transition to COMPLETED."""
    payload = {
        "course_name": "DevOps Foundations",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "Dev 1", "email": "dev1@example.com"},
            {"name": "Dev 2", "email": "dev2@example.com"},
        ],
    }

    res = client.post("/api/v1/jobs", json=payload)
    job_id = res.json()["job_id"]

    status_res = client.get(f"/api/v1/jobs/{job_id}")
    data = status_res.json()

    assert data["status"] == JobStatus.COMPLETED.value
    assert data["total_count"] == 2
    assert data["success_count"] == 2
    assert data["failed_count"] == 0
    assert data["pending_count"] == 0
    assert data["progress_percentage"] == 100.0


def test_job_status_all_failed(client):
    """Job where all recipients are invalid should finalize as FAILED."""
    payload = {
        "course_name": "DevOps Foundations",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "", "email": "bad1"},
            {"name": "   ", "email": "bad2"},
        ],
    }

    res = client.post("/api/v1/jobs", json=payload)
    job_id = res.json()["job_id"]

    status_res = client.get(f"/api/v1/jobs/{job_id}")
    data = status_res.json()

    assert data["status"] == JobStatus.FAILED.value
    assert data["total_count"] == 2
    assert data["success_count"] == 0
    assert data["failed_count"] == 2
    assert data["progress_percentage"] == 100.0


def test_job_pagination_and_deterministic_order(client):
    """
    Verifies that:
    1. Results are returned in deterministic original request order (position).
    2. Pagination (page and page_size <= 100) functions correctly.
    """
    recipients = [
        {"name": f"Candidate {i:02d}", "email": f"cand{i:02d}@example.com"}
        for i in range(15)
    ]
    payload = {
        "course_name": "Distributed Systems",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": recipients,
    }

    res = client.post("/api/v1/jobs", json=payload)
    job_id = res.json()["job_id"]

    # Page 1 (first 10 items)
    p1_res = client.get(f"/api/v1/jobs/{job_id}?page=1&page_size=10")
    assert p1_res.status_code == 200
    p1_data = p1_res.json()
    assert p1_data["page"] == 1
    assert p1_data["page_size"] == 10
    assert p1_data["total_pages"] == 2
    assert len(p1_data["recipients"]) == 10

    # Verify deterministic request order on page 1
    for idx, item in enumerate(p1_data["recipients"]):
        assert item["position"] == idx
        assert item["recipient_name"] == f"Candidate {idx:02d}"

    # Page 2 (remaining 5 items)
    p2_res = client.get(f"/api/v1/jobs/{job_id}?page=2&page_size=10")
    assert p2_res.status_code == 200
    p2_data = p2_res.json()
    assert len(p2_data["recipients"]) == 5

    for idx, item in enumerate(p2_data["recipients"], start=10):
        assert item["position"] == idx
        assert item["recipient_name"] == f"Candidate {idx:02d}"
