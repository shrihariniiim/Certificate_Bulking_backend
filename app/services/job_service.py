import logging
import uuid
from typing import Callable, Optional, Set, Union
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Certificate, CertificateStatus, Job, JobStatus, utc_now
from app.schemas import EMAIL_REGEX, JobCreateRequest
from app.services.certificate_generator import generate_certificate_pdf
from app.services.storage import StorageService, default_storage

logger = logging.getLogger(__name__)


def validate_recipient(
    name: str,
    email: str,
    seen_emails: Set[str],
    max_name_length: int,
) -> tuple[bool, Optional[str], str]:
    """
    Tier 2 (Recipient-level) validation.
    Checks recipient data individually:
    - Empty or whitespace-only name
    - Name exceeding maximum length
    - Invalid email format
    - Duplicate email within the same bulk request batch (normalized)

    Returns:
    (is_valid: bool, error_message: Optional[str], normalized_email: str)
    """
    cleaned_name = name.strip() if name else ""
    norm_email = email.strip().lower() if email else ""

    if not cleaned_name:
        return False, "Recipient name cannot be empty or whitespace only", norm_email

    if len(cleaned_name) > max_name_length:
        return (
            False,
            f"Recipient name exceeds maximum allowed length of {max_name_length} characters",
            norm_email,
        )

    if not norm_email or not EMAIL_REGEX.match(norm_email):
        return False, f"Invalid email format: '{email}'", norm_email

    if norm_email in seen_emails:
        return (
            False,
            f"Duplicate email within the same request batch: '{norm_email}'",
            norm_email,
        )

    return True, None, norm_email


def create_bulk_job(db: Session, request: JobCreateRequest) -> Job:
    """
    Creates the parent Job and all recipient Certificate rows in ONE single atomic transaction.
    Performs recipient-level validation:
    - Valid recipients are saved with status PENDING.
    - Invalid recipients are immediately saved with status FAILED and their error reason.
    This guarantees that malformed recipients never cancel or delay the valid ones.
    """
    settings = get_settings()

    # Initialize parent Job record
    job = Job(
        course_name=request.course_name,
        organization_name=request.organization_name,
        issue_date=request.issue_date,
        status=JobStatus.PENDING.value,
        total_count=len(request.recipients),
        success_count=0,
        failed_count=0,
    )
    db.add(job)
    db.flush()  # Generates job.id so foreign keys can attach

    seen_emails: Set[str] = set()

    for idx, item in enumerate(request.recipients):
        is_valid, err_msg, norm_email = validate_recipient(
            name=item.name,
            email=item.email,
            seen_emails=seen_emails,
            max_name_length=settings.max_name_length,
        )

        if is_valid:
            seen_emails.add(norm_email)
            cert = Certificate(
                job_id=job.id,
                position=idx,
                recipient_name=item.name.strip(),
                recipient_email=norm_email,
                status=CertificateStatus.PENDING.value,
            )
        else:
            # Mark recipient as FAILED immediately at inception
            job.failed_count += 1
            cert = Certificate(
                job_id=job.id,
                position=idx,
                recipient_name=item.name if item.name is not None else "",
                recipient_email=item.email if item.email is not None else "",
                status=CertificateStatus.FAILED.value,
                error_message=err_msg,
                completed_at=utc_now(),
            )

        db.add(cert)

    # Commit the entire batch atomically
    db.commit()
    db.refresh(job)
    return job


def process_job(
    job_id: Union[uuid.UUID, str],
    session_factory: Optional[Callable[[], Session]] = None,
    storage: Optional[StorageService] = None,
) -> None:
    """
    Background worker executing certificate generation.
    DESIGN GUARANTEES:
    1. Independent Session: Opens and closes its OWN database session, decoupled from HTTP request.
    2. Importable & Synchronous-Ready: Directly callable by pytest or test harnesses.
    3. Incremental Per-Item Commits: Updates job counters with each certificate, enabling live progress tracking.
    4. Per-Item Isolation: PDF generation crashes on one item rollback only that item and mark it FAILED.
    5. Write File First: PDF is successfully written to storage before marking SUCCESS in DB.
    6. Non-blocking Stalled Prevention: Top-level exception handling guarantees job is never stuck in PROCESSING.
    """
    job_uuid = uuid.UUID(str(job_id)) if not isinstance(job_id, uuid.UUID) else job_id
    factory = session_factory or SessionLocal
    storage_svc = storage or default_storage

    db = factory()
    try:
        job = db.get(Job, job_uuid)
        if not job:
            logger.error(f"process_job: Job {job_uuid} not found")
            return

        # If all items were invalid at creation time, finalize immediately as FAILED
        if job.failed_count == job.total_count:
            job.status = JobStatus.FAILED.value
            job.completed_at = utc_now()
            db.commit()
            return

        # Transition job to PROCESSING
        job.status = JobStatus.PROCESSING.value
        job.started_at = utc_now()
        db.commit()

        # Query only PENDING items to process in original request order
        stmt = (
            select(Certificate)
            .where(
                Certificate.job_id == job_uuid,
                Certificate.status == CertificateStatus.PENDING.value,
            )
            .order_by(Certificate.position)
        )
        pending_certs = list(db.scalars(stmt).all())

        for cert in pending_certs:
            try:
                # 1. Pure PDF generation (in-memory)
                pdf_bytes = generate_certificate_pdf(
                    recipient_name=cert.recipient_name,
                    course_name=job.course_name,
                    organization_name=job.organization_name,
                    issue_date=job.issue_date,
                    certificate_id=cert.id,
                )

                # 2. Write file to disk atomically before updating DB
                rel_path = storage_svc.save_certificate_pdf(
                    certificate_id=cert.id,
                    pdf_bytes=pdf_bytes,
                )

                # 3. Update certificate state to SUCCESS
                cert.status = CertificateStatus.SUCCESS.value
                cert.file_path = rel_path
                cert.completed_at = utc_now()

                # 4. Increment job success counter in the SAME commit
                job.success_count += 1
                db.commit()

            except Exception as item_err:
                # Per-item error isolation: rollback this item's transaction
                logger.warning(
                    f"Error generating certificate for {cert.recipient_name} ({cert.id}): {item_err}"
                )
                db.rollback()

                # Re-fetch or re-bind objects and record failure
                cert.status = CertificateStatus.FAILED.value
                cert.error_message = f"Generation failed: {str(item_err)[:250]}"
                cert.completed_at = utc_now()
                job.failed_count += 1
                db.commit()

        # Final Job status evaluation
        if job.success_count == job.total_count:
            job.status = JobStatus.COMPLETED.value
        elif job.success_count == 0:
            job.status = JobStatus.FAILED.value
        else:
            job.status = JobStatus.COMPLETED_WITH_ERRORS.value

        job.completed_at = utc_now()
        db.commit()

    except Exception as fatal_err:
        # Top-level failure handling: ensures the job is NEVER left in PROCESSING state
        logger.error(f"Fatal error processing job {job_uuid}: {fatal_err}", exc_info=True)
        try:
            db.rollback()
            job = db.get(Job, job_uuid)
            if job and job.status == JobStatus.PROCESSING.value:
                job.status = JobStatus.FAILED.value
                job.completed_at = utc_now()
                db.commit()
        except Exception:
            logger.critical(f"Failed to record fatal failure for job {job_uuid}", exc_info=True)
    finally:
        db.close()


def recover_stale_jobs(session_factory: Optional[Callable[[], Session]] = None) -> int:
    """
    Startup recovery function.
    Finds any jobs that were left in PROCESSING state (e.g. if the server restarted mid-job)
    and marks them FAILED so clients are not left waiting forever.
    Returns the number of stale jobs recovered.
    """
    factory = session_factory or SessionLocal
    db = factory()
    recovered_count = 0
    try:
        stmt = select(Job).where(Job.status == JobStatus.PROCESSING.value)
        stale_jobs = list(db.scalars(stmt).all())
        for job in stale_jobs:
            job.status = JobStatus.FAILED.value
            job.completed_at = utc_now()

            # Mark any remaining PENDING or PROCESSING certificates as FAILED
            cert_stmt = select(Certificate).where(
                Certificate.job_id == job.id,
                Certificate.status.in_([
                    CertificateStatus.PENDING.value,
                    CertificateStatus.PROCESSING.value,
                ]),
            )
            for cert in db.scalars(cert_stmt).all():
                cert.status = CertificateStatus.FAILED.value
                cert.error_message = "Server restarted while job was in progress"
                cert.completed_at = utc_now()
                job.failed_count += 1

            recovered_count += 1

        if recovered_count > 0:
            db.commit()
            logger.info(f"Recovered {recovered_count} stale PROCESSING jobs on startup")
    except Exception as e:
        logger.error(f"Error during recover_stale_jobs: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

    return recovered_count
