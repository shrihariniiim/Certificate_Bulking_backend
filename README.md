# Bulk Certificate Generator API

A backend API that accepts **one request containing many recipients**, generates a PDF certificate for each valid recipient from a single predefined template, tracks progress per job and per certificate, and lets the client download the results individually or as a ZIP.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, ReportLab, SQLite (PostgreSQL-ready), pytest.

---

## Table of contents

1. [Setup](#1-setup)
2. [Run the application](#2-run-the-application)
3. [Run the tests](#3-run-the-tests)
4. [API overview](#4-api-overview)
5. [Usage examples](#5-usage-examples)
6. [How it works](#6-how-it-works)
7. [Validation and failure handling](#7-validation-and-failure-handling)
8. [Design decisions](#8-design-decisions)
9. [Configuration](#9-configuration)
10. [Database schema](#10-database-schema)
11. [Switching to PostgreSQL](#11-switching-to-postgresql)
12. [Project structure](#12-project-structure)
13. [Known limitations](#13-known-limitations)
14. [Possible improvements](#14-possible-improvements)
15. [AI assistance and licenses](#15-ai-assistance-and-licenses)

---

## 1. Setup

Requirements: Python 3.11+ and Git.

```bash
git clone https://github.com/shrihariniiim/Certificate_Bulking_backend.git
cd Certificate_Bulking_backend

python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (cmd)
.venv\Scripts\activate.bat
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

No `.env` file is needed. Defaults work out of the box (see [Configuration](#9-configuration)).

## 2. Run the application

```bash
uvicorn app.main:app --reload
```

| URL | Purpose |
| --- | --- |
| http://127.0.0.1:8000/docs | Swagger UI. Try every endpoint in the browser |
| http://127.0.0.1:8000/redoc | Read-only API documentation |
| http://127.0.0.1:8000/health | Health check (returns 503 if the database is unreachable) |

On first start the app creates the SQLite database at `storage/app.db`. Generated PDFs are written to `storage/certificates/<certificate_id>.pdf`.

> There are no migrations. If you change the models, delete `storage/app.db` and restart.

## 3. Run the tests

```bash
pytest -v
```

Every test runs against a temporary SQLite database and a temporary storage folder, so your real data is not used. The suite covers:

- creating a job (202 response, rows saved)
- request-level and recipient-level validation
- PDF generation (valid PDF, recipient name present, English / Tamil / Hindi)
- job status and progress counters
- failure of a single certificate not affecting the others
- retrieving a single PDF and the ZIP (200, 404, 409)
- a mixed valid/invalid bulk request of 50 recipients

## 4. API overview

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/jobs` | Create a bulk generation job. Returns **202** immediately |
| GET | `/api/v1/jobs/{job_id}` | Job status, progress counters and per-recipient results (paginated) |
| GET | `/api/v1/jobs/{job_id}/certificates` | List a job's certificates. Optional `?status=SUCCESS` / `FAILED` |
| GET | `/api/v1/certificates/{certificate_id}/download` | Download one certificate as PDF |
| GET | `/api/v1/jobs/{job_id}/download` | Download all successful certificates as a ZIP |
| GET | `/health` | Application and database health |

Pagination parameters: `page` (>= 1, default 1) and `page_size` (1 to 100, default 50).

**Status codes:** `202` job accepted, `200` OK, `404` not found, `409` not ready or failed, `422` invalid request, `503` database unavailable.
Errors are returned as `{"detail": "..."}`.

## 5. Usage examples

### Submit a job

Save this as `request.json`:

```json
{
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
}
```

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @request.json
```

On Windows PowerShell use `curl.exe` (plain `curl` is an alias for something else):

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/jobs -H "Content-Type: application/json" -d "@request.json"
```

Response (`202 Accepted`):

```json
{
  "job_id": "5d468d0d-1f32-4e47-a279-9b07d5f5bef1",
  "status": "PENDING",
  "total_count": 5,
  "message": "Bulk certificate generation job accepted and processing in background",
  "links": {
    "status": "/api/v1/jobs/5d468d0d-1f32-4e47-a279-9b07d5f5bef1",
    "certificates": "/api/v1/jobs/5d468d0d-1f32-4e47-a279-9b07d5f5bef1/certificates",
    "download_all": "/api/v1/jobs/5d468d0d-1f32-4e47-a279-9b07d5f5bef1/download"
  }
}
```

### Check status and progress

```bash
curl "http://127.0.0.1:8000/api/v1/jobs/<job_id>?page=1&page_size=50"
```

Response (`200 OK`, recipient list shortened here; IDs and timestamps will differ on your machine):

```json
{
  "job_id": "5d468d0d-1f32-4e47-a279-9b07d5f5bef1",
  "course_name": "Fullstack Python Mastery",
  "organization_name": "Aereo Academy",
  "issue_date": "2026-10-08",
  "status": "COMPLETED_WITH_ERRORS",
  "total_count": 5,
  "success_count": 2,
  "failed_count": 3,
  "pending_count": 0,
  "progress_percentage": 100.0,
  "created_at": "2026-10-08T14:48:42.583876",
  "started_at": "2026-10-08T14:48:42.697149",
  "completed_at": "2026-10-08T14:48:43.070435",
  "page": 1,
  "page_size": 50,
  "total_pages": 1,
  "recipients": [
    {
      "id": "eac0d922-a46a-4313-bb3a-3d489703fe4a",
      "position": 0,
      "recipient_name": "Alice Walker",
      "recipient_email": "alice@example.com",
      "status": "SUCCESS",
      "error_message": null,
      "download_url": "/api/v1/certificates/eac0d922-a46a-4313-bb3a-3d489703fe4a/download"
    },
    {
      "id": "cba584a1-e0a3-49ac-b36f-861b0c47e2ef",
      "position": 3,
      "recipient_name": "Bob Marley",
      "recipient_email": "invalid-email",
      "status": "FAILED",
      "error_message": "Invalid email format: 'invalid-email'",
      "download_url": null
    }
  ],
  "links": { "self": "...", "certificates": "...", "download_all": "..." }
}
```

Poll this endpoint until `status` is `COMPLETED`, `COMPLETED_WITH_ERRORS` or `FAILED`.

### List certificates (optionally filtered)

```bash
curl "http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates?status=FAILED"
```

### Download certificates

```bash
# One certificate
curl http://127.0.0.1:8000/api/v1/certificates/<certificate_id>/download -o certificate.pdf

# All successful certificates of a job
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>/download -o certificates.zip
```

Files inside the ZIP are named `<recipient_name>_<short_id>.pdf`, so two people with the same name never collide.

## 6. How it works

```
POST /api/v1/jobs
   |
   |-- 1. Request-level validation (Pydantic)            -> 422 if invalid
   |-- 2. Create the job and ALL recipient rows in one DB transaction
   |        valid recipients   -> status PENDING
   |        invalid recipients -> status FAILED + error message
   |-- 3. Queue process_job(job_id) with FastAPI BackgroundTasks
   '-- 4. Return 202 with the job_id

Background worker: process_job(job_id)
   |-- opens its OWN database session
   |-- job -> PROCESSING
   |-- for each PENDING certificate, in request order:
   |      generate PDF in memory -> write file to disk -> mark SUCCESS
   |      (any error: mark only this certificate FAILED and continue)
   |      commit after every certificate, so progress is visible live
   '-- final status: COMPLETED / COMPLETED_WITH_ERRORS / FAILED
```

**Job statuses:** `PENDING` -> `PROCESSING` -> `COMPLETED` (all succeeded), `COMPLETED_WITH_ERRORS` (some failed) or `FAILED` (none succeeded, including a request where every recipient was invalid).

**Certificate statuses:** `PENDING`, `SUCCESS`, `FAILED`.

The certificate design (landscape page, double border, title, recipient name, course, issue date, signature line and certificate ID) is drawn in code in `app/services/certificate_generator.py`. There is no template file or editor. The generator is a pure function: plain values in, PDF bytes out, no database or file access.

## 7. Validation and failure handling

**Request-level (the whole request is rejected with 422):**

- `recipients` is empty or longer than `MAX_RECIPIENTS` (default 1000)
- `course_name` or `organization_name` is missing or blank
- `issue_date` is not a valid date (`YYYY-MM-DD`)
- the body is not valid JSON

**Recipient-level (that recipient is saved as FAILED, the others continue):**

- empty or whitespace-only name
- name longer than `MAX_NAME_LENGTH` (default 100)
- invalid email format
- duplicate email within the same request (compared case-insensitively, the first occurrence wins)

**Generation failures:** an error while rendering or saving one certificate marks only that certificate FAILED with a short error message. The rest of the job continues. The job status shows how many succeeded and failed, and the per-recipient list shows the reason for each failure.

## 8. Design decisions

**Background processing instead of synchronous generation.**
A request may contain up to 1000 recipients. Generating them inside the request would be slow and could time out, so the API saves the job, returns `202` with a `job_id`, and processes in the background. The client polls the status endpoint.

**FastAPI `BackgroundTasks`, not Celery/Redis.**
It needs no extra services, which keeps the project easy to run and explain. The trade-off is that the queue lives in memory and is lost if the process stops (see [Known limitations](#13-known-limitations)). `process_job` receives only a `job_id` and opens its own database session, so moving it to Celery or RQ later only changes how it is called, not the worker itself.

**Validation in two tiers.**
Pydantic checks only the request structure. Recipient `name` and `email` are plain strings in the schema on purpose: if Pydantic validated them, one bad recipient would reject the whole request. Recipient checks run in `job_service.py` so invalid recipients become FAILED rows while valid ones proceed.

**Per-item isolation and progress.**
Each certificate is committed separately, together with the job counters. A failure rolls back only that item. The PDF file is written to disk before the row is marked SUCCESS, so a SUCCESS row always has a file.

**Safe file storage.**
Files are named `<certificate_id>.pdf` only (never from user input). The database stores the relative path. Writes go to a temporary file followed by an atomic rename. Reads resolve the path and refuse anything outside the storage folder.

**Deterministic ordering.**
Each certificate has a `position` column (its index in the request), and results are always returned in that order.

**Unicode names.**
Noto Sans, Noto Sans Tamil and Noto Sans Devanagari are bundled in `app/assets/fonts/`. The font is chosen per text by Unicode range, and long names are shrunk to fit the page.

**Database-agnostic.**
SQLAlchemy 2.0 with generic types (`Uuid`, `String`, `Date`, ...). Switching to PostgreSQL only needs a new `DATABASE_URL`.

**Dependency injection for testability.**
The database session, the session factory used by the worker, and the storage service are FastAPI dependencies, so tests replace them with temporary ones.

## 9. Configuration

Set through environment variables or a `.env` file (see `.env.example`).

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./storage/app.db` | SQLAlchemy connection string |
| `STORAGE_DIR` | `./storage/certificates` | Where generated PDFs are saved |
| `MAX_RECIPIENTS` | `1000` | Maximum recipients per request (above this: 422) |
| `MAX_NAME_LENGTH` | `100` | Maximum recipient name length (above this: that recipient fails) |
| `APP_TITLE` | `Bulk Certificate Generator API` | API title shown in the docs |
| `APP_VERSION` | `1.0.0` | API version |

## 10. Database schema

**`jobs`**: `id` (UUID, PK), `course_name`, `organization_name`, `issue_date`, `status`, `total_count`, `success_count`, `failed_count`, `created_at`, `started_at`, `completed_at`.

**`certificates`**: `id` (UUID, PK), `job_id` (FK to `jobs`), `position`, `recipient_name`, `recipient_email`, `status`, `error_message`, `file_path`, `created_at`, `completed_at`.

Indexes: `certificates.job_id`, `certificates.status`, a composite `(job_id, status)` for filtered listings, and `jobs.status`.

## 11. Switching to PostgreSQL

```bash
pip install "psycopg[binary]"
```

```ini
# .env
DATABASE_URL=postgresql+psycopg://username:password@localhost:5432/certificates_db
```

Restart the app. Tables are created automatically on startup. For production, add a migration tool (Alembic) instead of relying on automatic table creation.

## 12. Project structure

```
app/
  main.py                      App creation, error handlers, /health, startup recovery
  config.py                    Settings from environment variables
  database.py                  Engine, session factory, dependencies
  models.py                    Job and Certificate tables
  schemas.py                   Request/response models
  routers/
    jobs.py                    Job endpoints
    certificates.py            Single certificate download
  services/
    job_service.py             Job creation, recipient validation, background worker
    certificate_generator.py   PDF template (pure function)
    storage.py                 Safe file storage and ZIP building
  assets/fonts/                Bundled Noto fonts
tests/                         pytest suite (temporary DB and storage per test)
DESIGN.md                      Extended design notes
```

## 13. Known limitations

1. **Jobs are not durable.** `BackgroundTasks` keeps work in memory. If the server stops mid-job, unfinished work is not resumed. On startup, `recover_stale_jobs()` marks jobs left in `PROCESSING` (and their unfinished certificates) as `FAILED` so clients are not left waiting. Such jobs must be resubmitted.
2. **Single process only.** The recovery step assumes one server process. With several workers, one could mark another's running job as failed. Horizontal scaling needs a real queue (Celery/RQ with Redis) and shared storage (for example S3).
3. **No complex-script shaping.** ReportLab places glyphs one by one. Tamil and Devanagari text may not form all ligatures and vowel signs the way a shaping engine would. Check rendered certificates for the scripts you need.
4. **Mixed-script names.** One font is chosen per text. A name mixing, for example, Latin and Tamil may show missing-glyph boxes for part of it.
5. **No authentication.** Anyone who knows a certificate ID can download it. Deploy behind a gateway that handles authentication, TLS and rate limiting.
6. **No migrations.** Tables are created with `create_all`. Schema changes need a manual reset or Alembic.
7. **ZIP is built in memory.** This is fine for 1000 certificates of about 20 KB each. Larger scale would need streaming or object storage.

## 14. Possible improvements

- Resume unfinished jobs on startup, and add a retry endpoint for failed certificates
- Celery/RQ with Redis, and S3 storage
- CSV upload as a second way to submit recipients (parsed into the same request model, same validation)
- Uploadable certificate templates using the overlay method (template file plus text overlay), with stored field positions
- Email delivery of generated certificates
- API-key authentication and rate limiting
- Alembic migrations

## 15. AI assistance and licenses

This project was built with AI tools (Google DeepMind Antigravity) for implementation and testing. The design, code and behavior are understood and can be explained and modified by the author.

The bundled fonts in `app/assets/fonts/` (`NotoSans-Regular.ttf`, `NotoSansTamil-Regular.ttf`, `NotoSansDevanagari-Regular.ttf`) are created by Google and licensed under the [SIL Open Font License 1.1](https://openfontlicense.org).

![alt text](image.png)
generted certificate image 
![alt text](image-1.png)
