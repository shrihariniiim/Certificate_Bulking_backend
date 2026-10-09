import io
import uuid
import zipfile
from pypdf import PdfReader
from app.models import CertificateStatus, JobStatus


def test_download_single_certificate_success(client):
    """Verifies downloading an individual certificate PDF."""
    payload = {
        "course_name": "API Security",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [{"name": "Neo Anderson", "email": "neo@matrix.org"}],
    }

    res = client.post("/api/v1/jobs", json=payload)
    job_id = res.json()["job_id"]

    # Get certificate ID
    status_res = client.get(f"/api/v1/jobs/{job_id}")
    cert_id = status_res.json()["recipients"][0]["id"]

    # Download PDF
    dl_res = client.get(f"/api/v1/certificates/{cert_id}/download")
    assert dl_res.status_code == 200
    assert dl_res.headers["content-type"] == "application/pdf"
    assert dl_res.content.startswith(b"%PDF")

    # Read PDF text
    reader = PdfReader(io.BytesIO(dl_res.content))
    assert "Neo Anderson" in reader.pages[0].extract_text()


def test_download_single_certificate_404_and_409(client, db_session):
    """
    Verifies:
    - 404 for non-existent certificate ID.
    - 409 for failed or pending certificate.
    """
    # 1. 404 for unknown ID
    unknown_id = uuid.uuid4()
    not_found = client.get(f"/api/v1/certificates/{unknown_id}/download")
    assert not_found.status_code == 404
    assert "not found" in not_found.json()["detail"].lower()

    # 2. 409 for failed recipient
    payload = {
        "course_name": "API Security",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "Valid", "email": "valid@example.com"},
            {"name": "", "email": "empty@example.com"},  # Failed item
        ],
    }
    res = client.post("/api/v1/jobs", json=payload)
    job_id = res.json()["job_id"]
    status_res = client.get(f"/api/v1/jobs/{job_id}")
    failed_cert_id = status_res.json()["recipients"][1]["id"]

    conflict_res = client.get(f"/api/v1/certificates/{failed_cert_id}/download")
    assert conflict_res.status_code == 409
    assert "failed" in conflict_res.json()["detail"].lower()


def test_download_zip_archive_success(client):
    """Verifies downloading all successful certificates bundled in a ZIP archive."""
    payload = {
        "course_name": "Cloud Native Architecture",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "Alice Smith", "email": "alice@example.com"},
            {"name": "Bob Jones", "email": "bob@example.com"},
            {"name": "", "email": "bad@example.com"},  # Fails, so excluded from ZIP
        ],
    }

    res = client.post("/api/v1/jobs", json=payload)
    job_id = res.json()["job_id"]

    # Download ZIP
    zip_res = client.get(f"/api/v1/jobs/{job_id}/download")
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"] == "application/zip"

    # Inspect ZIP contents
    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as z:
        names = z.namelist()
        # Exactly 2 successful files
        assert len(names) == 2
        assert any("alice_smith" in n.lower() for n in names)
        assert any("bob_jones" in n.lower() for n in names)


def test_mixed_validity_bulk_50_recipients(client):
    """
    Stress test with 50 mixed recipients:
    - 30 valid unique recipients
    - 5 empty names
    - 5 malformed emails
    - 10 duplicate emails
    Verifies that the API processes all 50 items deterministically and creates the ZIP.
    """
    recipients = []
    # 30 valid
    for i in range(30):
        recipients.append({"name": f"Valid Student {i}", "email": f"student{i}@university.edu"})
    # 5 empty names
    for i in range(5):
        recipients.append({"name": "", "email": f"empty{i}@university.edu"})
    # 5 malformed emails
    for i in range(5):
        recipients.append({"name": f"Bad Email {i}", "email": f"invalid-email-{i}"})
    # 10 duplicate emails (duplicates of student0..9)
    for i in range(10):
        recipients.append({"name": f"Duplicate Student {i}", "email": f"STUDENT{i}@university.edu"})

    payload = {
        "course_name": "University Large Scale Training",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": recipients,
    }

    res = client.post("/api/v1/jobs", json=payload)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Fetch status
    status_res = client.get(f"/api/v1/jobs/{job_id}?page_size=100")
    assert status_res.status_code == 200
    data = status_res.json()

    assert data["total_count"] == 50
    assert data["success_count"] == 30
    assert data["failed_count"] == 20
    assert data["status"] == JobStatus.COMPLETED_WITH_ERRORS.value
    assert data["progress_percentage"] == 100.0

    # Verify ZIP has exactly 30 PDFs
    zip_res = client.get(f"/api/v1/jobs/{job_id}/download")
    assert zip_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as z:
        assert len(z.namelist()) == 30


def test_same_name_zip_entries_unique(client):
    """
    Verifies that when two distinct recipients share the exact same name,
    their entries inside the ZIP archive do not collide and have unique filenames
    (due to short certificate UUID suffixing).
    """
    payload = {
        "course_name": "Name Collision Defense",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [
            {"name": "John Smith", "email": "john1@example.com"},
            {"name": "John Smith", "email": "john2@example.com"},
        ],
    }

    res = client.post("/api/v1/jobs", json=payload)
    job_id = res.json()["job_id"]

    zip_res = client.get(f"/api/v1/jobs/{job_id}/download")
    assert zip_res.status_code == 200

    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as z:
        names = z.namelist()
        assert len(names) == 2
        assert names[0] != names[1]
        assert all(n.lower().startswith("john_smith_") and n.endswith(".pdf") for n in names)


def test_tamil_name_extracted_from_job_pdf(client):
    """
    Verifies that a job created with a Tamil recipient name produces a downloadable PDF
    from which the exact Tamil Unicode text can be extracted via pypdf.
    """
    tamil_name = "அரவிந்த் குமார்"
    payload = {
        "course_name": "Tamil Language Data Processing",
        "organization_name": "Aereo Academy",
        "issue_date": "2026-10-08",
        "recipients": [{"name": tamil_name, "email": "aravind@example.com"}],
    }

    res = client.post("/api/v1/jobs", json=payload)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    status_res = client.get(f"/api/v1/jobs/{job_id}")
    cert_id = status_res.json()["recipients"][0]["id"]

    dl_res = client.get(f"/api/v1/certificates/{cert_id}/download")
    assert dl_res.status_code == 200
    assert dl_res.content.startswith(b"%PDF")

    reader = PdfReader(io.BytesIO(dl_res.content))
    extracted = reader.pages[0].extract_text()
    assert tamil_name in extracted

