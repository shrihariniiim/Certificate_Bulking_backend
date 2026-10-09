# Bulk Certificate Generator API — Architecture & System Design

## 1. System Overview

The **Bulk Certificate Generator API** is designed for asynchronous bulk processing of PDF certificates from a single request. It balances high throughput, strict failure isolation, and architectural simplicity without introducing heavy distributed dependencies (like Celery/Redis) upfront.

```
                      +---------------------------------------+
                      |               Client                  |
                      +---------------------------------------+
                           | POST /jobs             | GET /jobs/{id}
                           v (HTTP 202)             v (Status / Download)
                      +---------------------------------------+
                      |            FastAPI API Layer          |
                      +---------------------------------------+
                           |                        |
                           | 1. Validate & Store    | 2. Enqueue Job
                           v                        v
                      +----------------+   +----------------------+
                      |  SQLAlchemy 2  |   | Background Worker    |
                      |  (SQLite/PgSQL)|   | (Session per job)    |
                      +----------------+   +----------------------+
                                                    |
                         +--------------------------+--------------------------+
                         |                                                     |
                         v                                                     v
          +-----------------------------+                       +-----------------------------+
          | ReportLab PDF Generator     |                       | Storage Service             |
          | - Vector borders            |                       | - Atomic writes (.tmp->.pdf)|
          | - Dynamic font selection    |                       | - Path traversal protection |
          | - Pure function (no I/O)    |                       | - In-memory ZIP packaging   |
          +-----------------------------+                       +-----------------------------+
```

---

## 2. Core Design Decisions

### 2.1 Background Processing vs Synchronous Processing
- **Why Background Processing?**
  Generating PDFs using ReportLab requires ~10–30ms of CPU time per certificate. For a bulk request of 100 to 1,000 recipients, synchronous processing would block the HTTP connection for 10 to 30 seconds, exceeding client timeouts (such as cloud load balancer 30s limits) and exhausting web worker concurrency.
- **Implementation:**
  `POST /api/v1/jobs` persists the Job and all recipient rows in one transaction and immediately returns `HTTP 202 Accepted` with a `job_id` and hypermedia links. Generation executes asynchronously using FastAPI's `BackgroundTasks`.
- **Known Limitations:**
  - **In-Memory Concurrency:** Background tasks run inside the same Python process. If the server is killed or restarted mid-job, in-progress jobs are terminated.
  - **Single Machine:** Cannot scale across multiple worker nodes without a distributed broker.
- **Scaling Path:**
  Replace `BackgroundTasks.add_task` with a Celery/RQ task dispatching onto Redis/RabbitMQ, running workers on isolated compute instances.

### 2.2 Two-Tier Validation Strategy
To avoid all-or-nothing failures, validation is separated into two tiers:
1. **Tier 1: Request-Level Validation (FastAPI & Pydantic v2)**
   - Rejects the entire request (`HTTP 422`) if the request itself is malformed: empty recipient list, missing course name, missing organization name, or recipient count exceeding `MAX_RECIPIENTS` (default 1000).
   - `RecipientInput.name` and `email` are intentionally typed as plain unconstrained `str` at the Pydantic level so that a single typo never fails the entire batch at the API gateway.
2. **Tier 2: Recipient-Level Validation (`job_service.validate_recipient`)**
   - Evaluates each recipient independently during the initial database write.
   - Normalizes emails (`strip().lower()`) and catches: empty names, names exceeding `MAX_NAME_LENGTH` (100), malformed emails, and duplicate emails within the batch (first occurrence wins).
   - Invalid recipients are immediately recorded with status `FAILED` and an explicit `error_message`, while valid recipients proceed to `PENDING`.

### 2.3 Per-Item Error Isolation
- In `process_job`, the generation loop wraps each certificate in an isolated `try/except` block.
- If rendering or file writing fails for one recipient:
  1. The transaction for that item is rolled back (`db.rollback()`).
  2. The item is marked `FAILED` with the exact error message.
  3. The `job.failed_count` is incremented.
  4. The worker continues uninterrupted to the next recipient.
- Job status ends with `COMPLETED` (100% success), `COMPLETED_WITH_ERRORS` (mixed), or `FAILED` (0% success).

### 2.4 File Storage & Security Best Practices
- **UUID-Only Filenames:** Files are stored as `{certificate_id}.pdf` on disk. User input is never used directly in filesystem paths, eliminating Path Traversal vulnerabilities (OWASP Top 10).
- **Atomic File Writes:** The generator writes to a temporary file (`{certificate_id}.tmp`) in the storage folder, performs `os.fsync` to flush buffers to disk, and executes an atomic `os.replace` to the final `.pdf` path.
- **Containment Checks:** `StorageService.resolve_path()` verifies that all resolved paths remain strictly within `STORAGE_DIR`.
- **Archive File Naming:** Inside the ZIP download, files are formatted as `{sanitized_name}_{short_id}.pdf` for human readability without risk of collisions or directory traversal.

### 2.5 Typography & Multilingual Font Strategy
- Bundles Google Noto Sans TrueType fonts in `app/assets/fonts`:
  - `NotoSans-Regular.ttf` (Latin & symbols)
  - `NotoSansTamil-Regular.ttf` (Tamil script: U+0B80–U+0BFF)
  - `NotoSansDevanagari-Regular.ttf` (Devanagari/Hindi script: U+0900–U+097F)
- `select_font_for_text` inspects Unicode character ranges dynamically.
- `auto_shrink_font_size` uses `pdfmetrics.stringWidth` to gracefully downscale long recipient names (up to `MAX_NAME_LENGTH = 100`) from 30pt to 12pt so names never clip or overflow the certificate border.
- **Limitation Note:** ReportLab standard canvas strings require a single font family per call. For names mixing Latin and Indic scripts within the same string (e.g. "Dr. அரவிந்த்"), the font is selected based on detected non-Latin script ranges.

### 2.6 Startup Stale Job Recovery
- On server startup, the `lifespan` handler calls `recover_stale_jobs()`.
- Any job left in `PROCESSING` state from a prior crashed process is automatically transitioned to `FAILED` with a descriptive message ("Server restarted while job was in progress"), ensuring clients never stay blocked waiting indefinitely.

---

## 3. Scaling Roadmap

1. **Distributed Task Queue:** Replace `FastAPI.BackgroundTasks` with Celery + Redis.
2. **Object Storage:** Replace local disk storage with AWS S3, Google Cloud Storage, or MinIO using pre-signed download URLs.
3. **Database Migration:** Switch from local SQLite to Amazon RDS / PostgreSQL by updating `DATABASE_URL=postgresql+psycopg://...`.
