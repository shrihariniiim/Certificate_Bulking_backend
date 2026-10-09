# Bulk Certificate Generator API

A production-quality, asynchronous REST API for generating bulk PDF certificates from a single predefined template. Built with **FastAPI**, **SQLAlchemy 2.0**, **Pydantic v2**, and **ReportLab**.

---

## 1. Quickstart & Setup

### Prerequisites
- Python 3.11+
- Git

### Installation
```bash
# 1. Clone the repository and navigate into the project directory
cd Bulking

# 2. Create and activate a virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Windows (cmd):
.venv\Scripts\activate.bat

# 3. Install dependencies
pip install -r requirements.txt
```

### Running the API Server
```bash
# Start with Uvicorn (with hot reload enabled)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Once started, the interactive OpenAPI documentation is accessible at:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

### Running Tests
Execute the comprehensive test suite with `pytest`:
```bash
pytest -v
```

---

## 2. API Usage & Curl Examples

### A. Health Check
```bash
curl -X GET http://localhost:8000/health
```
**Response (200 OK):**
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "1.0.0"
}
```

---

### B. Submit a Bulk Generation Job
Submits a list of recipients for certificate generation. Returns immediately with HTTP 202 Accepted.

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "course_name": "Fullstack Python Mastery",
    "organization_name": "Aereo Academy",
    "issue_date": "2026-10-08",
    "recipients": [
      {"name": "Alice Walker", "email": "alice@example.com"},
      {"name": "அரவிந்த் குமார்", "email": "aravind@example.com"},
      {"name": "", "email": "bad-user@example.com"},
      {"name": "Bob Marley", "email": "invalid-email"},
      {"name": "Alice Duplicate", "email": "alice@example.com"}
    ]
  }'
```

**Response (202 Accepted):**
```json
{
  "job_id": "2184aed4-e11b-49b0-b715-3202abb47b1b",
  "status": "PENDING",
  "total_count": 5,
  "message": "Bulk certificate generation job accepted and processing in background",
  "links": {
    "status": "/api/v1/jobs/2184aed4-e11b-49b0-b715-3202abb47b1b",
    "certificates": "/api/v1/jobs/2184aed4-e11b-49b0-b715-3202abb47b1b/certificates",
    "download_all": "/api/v1/jobs/2184aed4-e11b-49b0-b715-3202abb47b1b/download"
  }
}
```

---

### C. Check Job Status & Live Progress
Poll the job status endpoint to inspect counters and recipient item outcomes.

```bash
curl -X GET "http://localhost:8000/api/v1/jobs/2184aed4-e11b-49b0-b715-3202abb47b1b?page=1&page_size=50"
```

**Response (200 OK):**
```json
{
  "job_id": "2184aed4-e11b-49b0-b715-3202abb47b1b",
  "course_name": "Fullstack Python Mastery",
  "organization_name": "Aereo Academy",
  "issue_date": "2026-10-08",
  "status": "COMPLETED_WITH_ERRORS",
  "total_count": 5,
  "success_count": 2,
  "failed_count": 3,
  "pending_count": 0,
  "progress_percentage": 100.0,
  "created_at": "2026-10-08T09:40:00Z",
  "started_at": "2026-10-08T09:40:01Z",
  "completed_at": "2026-10-08T09:40:02Z",
  "page": 1,
  "page_size": 50,
  "total_pages": 1,
  "recipients": [
    {
      "id": "d36571ee-de31-44d6-b7ce-83bb336fe82e",
      "position": 0,
      "recipient_name": "Alice Walker",
      "recipient_email": "alice@example.com",
      "status": "SUCCESS",
      "error_message": null,
      "download_url": "/api/v1/certificates/d36571ee-de31-44d6-b7ce-83bb336fe82e/download",
      "created_at": "2026-10-08T09:40:00Z",
      "completed_at": "2026-10-08T09:40:01Z"
    },
    {
      "id": "c04629d0-5a74-4a0b-b9a5-ca80ad66c7db",
      "position": 1,
      "recipient_name": "அரவிந்த் குமார்",
      "recipient_email": "aravind@example.com",
      "status": "SUCCESS",
      "error_message": null,
      "download_url": "/api/v1/certificates/c04629d0-5a74-4a0b-b9a5-ca80ad66c7db/download",
      "created_at": "2026-10-08T09:40:00Z",
      "completed_at": "2026-10-08T09:40:02Z"
    },
    {
      "id": "27063467-ad5f-47cf-8910-18e692120e2e",
      "position": 2,
      "recipient_name": "",
      "recipient_email": "bad-user@example.com",
      "status": "FAILED",
      "error_message": "Recipient name cannot be empty or whitespace only",
      "download_url": null,
      "created_at": "2026-10-08T09:40:00Z",
      "completed_at": "2026-10-08T09:40:00Z"
    },
    {
      "id": "90e3ab71-ca30-4e5a-8b1b-60783abdf152",
      "position": 3,
      "recipient_name": "Bob Marley",
      "recipient_email": "invalid-email",
      "status": "FAILED",
      "error_message": "Invalid email format: 'invalid-email'",
      "download_url": null,
      "created_at": "2026-10-08T09:40:00Z",
      "completed_at": "2026-10-08T09:40:00Z"
    },
    {
      "id": "c138dbd2-1c64-42f2-b7e6-799ffacba958",
      "position": 4,
      "recipient_name": "Alice Duplicate",
      "recipient_email": "alice@example.com",
      "status": "FAILED",
      "error_message": "Duplicate email within the same request batch: 'alice@example.com'",
      "download_url": null,
      "created_at": "2026-10-08T09:40:00Z",
      "completed_at": "2026-10-08T09:40:00Z"
    }
  ],
  "links": {
    "self": "/api/v1/jobs/2184aed4-e11b-49b0-b715-3202abb47b1b?page=1&page_size=50",
    "certificates": "/api/v1/jobs/2184aed4-e11b-49b0-b715-3202abb47b1b/certificates",
    "download_all": "/api/v1/jobs/2184aed4-e11b-49b0-b715-3202abb47b1b/download"
  }
}
```

---

### D. Download an Individual PDF Certificate
```bash
curl -X GET http://localhost:8000/api/v1/certificates/d36571ee-de31-44d6-b7ce-83bb336fe82e/download \
  -o certificate.pdf
```
- Returns `HTTP 200 OK` with `application/pdf` binary.
- Returns `HTTP 404` if the ID does not exist.
- Returns `HTTP 409` if the certificate generation is still processing or failed.

---

### E. Download All Certificates as a ZIP Archive
```bash
curl -X GET http://localhost:8000/api/v1/jobs/2184aed4-e11b-49b0-b715-3202abb47b1b/download \
  -o certificates.zip
```
- Returns `HTTP 200 OK` with `application/zip` bundle containing sanitized `{name}_{short_id}.pdf` files.
- Returns `HTTP 409 Conflict` if the job is still processing.

---

## 3. Environment Variables

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | string | `sqlite:///./storage/app.db` | SQLAlchemy connection string |
| `STORAGE_DIR` | string | `./storage/certificates` | Filesystem path for generated PDFs |
| `MAX_RECIPIENTS` | integer | `1000` | Request-level bulk limit (exceeding triggers 422) |
| `MAX_NAME_LENGTH` | integer | `100` | Recipient-level maximum name length |
| `APP_TITLE` | string | `Bulk Certificate Generator API` | OpenAPI metadata title |
| `APP_VERSION` | string | `1.0.0` | Application version |

---

## 4. Switching from SQLite to PostgreSQL

The codebase is built with database-agnostic SQLAlchemy 2.0 ORM patterns (no SQLite-specific features). To switch to PostgreSQL:

1. Install the official modern PostgreSQL DBAPI driver:
   ```bash
   pip install psycopg[binary]
   ```
2. Update the `DATABASE_URL` variable in `.env`:
   ```ini
   DATABASE_URL=postgresql+psycopg://username:password@localhost:5432/certificates_db
   ```
3. Restart the application. The SQLAlchemy `lifespan` handler automatically creates all required tables (`jobs`, `certificates`) and indexes on the PostgreSQL server.

---

## 5. Important Design Decisions

- **Background Processing vs. Synchronous Execution**: Synchronous bulk generation causes HTTP timeouts when batches exceed tens of recipients. Background processing returns `HTTP 202` within milliseconds while keeping database progress counters live.
- **Two-Tier Validation Strategy**: Pydantic handles request-level structure (rejecting empty batches or malformed payloads with 422). Individual recipient checks (empty names, bad emails, duplicates) are isolated in `job_service.py` so valid recipients are never blocked by bad entries.
- **Atomic File Storage & Traversal Prevention**: Files on disk are saved solely as `{uuid}.pdf`. Temporary files (`.tmp`) are flushed to disk before an atomic rename, and `StorageService.resolve_path()` prevents path traversal vulnerabilities.
- **Pure PDF Generator**: `services/certificate_generator.py` has zero DB or filesystem dependencies. It accepts plain values and returns pure PDF bytes, making testing trivial and thread-safe.
- **Deterministic Ordering**: Certificates have an explicit integer `position` column corresponding to their original index in the request payload.

---

## 6. Development & AI Assistance Disclosure

This project was built with the assistance of AI engineering tools (Google DeepMind Antigravity) to establish test-driven implementation patterns, Unicode TrueType font configuration, and architectural failure-isolation safeguards.

---

## 7. Font License

The bundled TrueType fonts in `app/assets/fonts/` (`NotoSans-Regular.ttf`, `NotoSansTamil-Regular.ttf`, `NotoSansDevanagari-Regular.ttf`) are created by Google and licensed under the **SIL Open Font License (OFL), Version 1.1** (https://openfontlicense.org).

