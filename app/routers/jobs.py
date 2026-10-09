import math
import uuid
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db, get_session_factory
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import (
    CertificateItemResponse,
    CertificateListResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
)
from app.services.job_service import create_bulk_job, process_job
from app.services.storage import StorageService, get_storage

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


@router.post(
    "",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a bulk certificate generation job",
    description=(
        "Accepts a bulk generation request for a list of recipients. "
        "Validates input, persists the job and all recipient records in one atomic transaction, "
        "and enqueues generation in the background. Returns HTTP 202 immediately."
    ),
)
def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    session_factory: sessionmaker = Depends(get_session_factory),
    storage: StorageService = Depends(get_storage),
):
    # 1. Atomically create parent Job and recipient Certificate items
    job = create_bulk_job(db, payload)

    # 2. Enqueue background execution passing the injected session factory and storage dependency
    background_tasks.add_task(process_job, job.id, session_factory=session_factory, storage=storage)

    # 3. Return 202 Accepted with hypermedia navigation links
    return JobCreateResponse(
        job_id=job.id,
        status=JobStatus(job.status),
        total_count=job.total_count,
        message="Bulk certificate generation job accepted and processing in background",
        links={
            "status": f"/api/v1/jobs/{job.id}",
            "certificates": f"/api/v1/jobs/{job.id}/certificates",
            "download_all": f"/api/v1/jobs/{job.id}/download",
        },
    )


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status and progress",
    description=(
        "Retrieves current job status, live progress counters, and a paginated list of recipient results."
    ),
)
def get_job_status(
    job_id: uuid.UUID,
    page: int = Query(1, ge=1, description="Page number for recipient items"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page (maximum 100)"),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Calculate pending count and completion percentage
    processed_count = job.success_count + job.failed_count
    pending_count = max(0, job.total_count - processed_count)
    progress_percentage = (
        round((processed_count / job.total_count) * 100, 1)
        if job.total_count > 0
        else 100.0
    )

    # Query paginated recipients for this job ordered deterministically by position
    offset = (page - 1) * page_size
    stmt = (
        select(Certificate)
        .where(Certificate.job_id == job_id)
        .order_by(Certificate.position)
        .offset(offset)
        .limit(page_size)
    )
    cert_records = list(db.scalars(stmt).all())
    total_pages = max(1, math.ceil(job.total_count / page_size))

    # Build response items including direct download links for successful items
    recipient_items = []
    for cert in cert_records:
        download_url = (
            f"/api/v1/certificates/{cert.id}/download"
            if cert.status == CertificateStatus.SUCCESS.value
            else None
        )
        recipient_items.append(
            CertificateItemResponse(
                id=cert.id,
                position=cert.position,
                recipient_name=cert.recipient_name,
                recipient_email=cert.recipient_email,
                status=CertificateStatus(cert.status),
                error_message=cert.error_message,
                download_url=download_url,
                created_at=cert.created_at,
                completed_at=cert.completed_at,
            )
        )

    return JobStatusResponse(
        job_id=job.id,
        course_name=job.course_name,
        organization_name=job.organization_name,
        issue_date=job.issue_date,
        status=JobStatus(job.status),
        total_count=job.total_count,
        success_count=job.success_count,
        failed_count=job.failed_count,
        pending_count=pending_count,
        progress_percentage=progress_percentage,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        recipients=recipient_items,
        links={
            "self": f"/api/v1/jobs/{job.id}?page={page}&page_size={page_size}",
            "certificates": f"/api/v1/jobs/{job.id}/certificates",
            "download_all": f"/api/v1/jobs/{job.id}/download",
        },
    )


@router.get(
    "/{job_id}/certificates",
    response_model=CertificateListResponse,
    summary="List certificates belonging to a job",
    description="Lists certificates for a job with optional status filtering and pagination.",
)
def list_job_certificates(
    job_id: uuid.UUID,
    status_filter: Optional[CertificateStatus] = Query(
        None, alias="status", description="Filter by certificate status (SUCCESS, FAILED, etc.)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page (maximum 100)"),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Base query for count and items
    base_query = select(Certificate).where(Certificate.job_id == job_id)
    if status_filter:
        base_query = base_query.where(Certificate.status == status_filter.value)

    # Total matching count
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total_matching = db.scalar(count_stmt) or 0

    # Paginated query ordered deterministically by position
    offset = (page - 1) * page_size
    items_stmt = base_query.order_by(Certificate.position).offset(offset).limit(page_size)
    certs = list(db.scalars(items_stmt).all())
    total_pages = max(1, math.ceil(total_matching / page_size))

    items = [
        CertificateItemResponse(
            id=c.id,
            position=c.position,
            recipient_name=c.recipient_name,
            recipient_email=c.recipient_email,
            status=CertificateStatus(c.status),
            error_message=c.error_message,
            download_url=f"/api/v1/certificates/{c.id}/download" if c.status == CertificateStatus.SUCCESS.value else None,
            created_at=c.created_at,
            completed_at=c.completed_at,
        )
        for c in certs
    ]

    return CertificateListResponse(
        job_id=job.id,
        total=total_matching,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=items,
    )


@router.get(
    "/{job_id}/download",
    summary="Download all successful certificates as a ZIP archive",
    description=(
        "Bundles all successfully generated certificates into a single ZIP archive. "
        "Returns HTTP 409 if the job is still processing."
    ),
)
def download_job_certificates_zip(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Cannot download ZIP while job is still pending or processing
    if job.status in (JobStatus.PENDING.value, JobStatus.PROCESSING.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Job is currently {job.status}. "
                "Bulk download is available once the job is COMPLETED or COMPLETED_WITH_ERRORS."
            ),
        )

    # Query all successful certificates ordered by recipient position
    stmt = (
        select(Certificate)
        .where(
            Certificate.job_id == job_id,
            Certificate.status == CertificateStatus.SUCCESS.value,
        )
        .order_by(Certificate.position)
    )
    successful_certs = list(db.scalars(stmt).all())

    if not successful_certs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No successful certificates available for download in this job",
        )

    # Build ZIP archive in memory ordered deterministically by position
    items_for_zip = [
        (c.recipient_name, c.file_path, c.id, c.position)
        for c in successful_certs
        if c.file_path
    ]
    zip_bytes = storage.build_certificates_zip(items_for_zip)

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="certificates_job_{job_id}.zip"',
            "Content-Type": "application/zip",
        },
    )
