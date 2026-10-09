import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import List, Optional
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobStatus(str, Enum):
    """
    Lifecycle states for a bulk generation job.
    - PENDING: Job created, queued for execution.
    - PROCESSING: Background worker actively generating certificates.
    - COMPLETED: Finished with all certificates successfully created.
    - COMPLETED_WITH_ERRORS: Finished with partial failures (some succeeded, some failed).
    - FAILED: Finished with zero certificates succeeded, or crashed completely.
    """
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class CertificateStatus(str, Enum):
    """
    Lifecycle states for individual recipient certificates.
    - PENDING: Awaiting validation / generation.
    - PROCESSING: Currently being rendered or written to disk.
    - SUCCESS: Successfully generated and PDF saved.
    - FAILED: Validation failed or PDF rendering crashed for this recipient.
    """
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


def utc_now() -> datetime:
    """Helper to return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class Job(Base):
    """
    Represents a bulk certificate generation batch.
    Stores high-level metadata, aggregate progress counters, and overall status.
    """
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the bulk generation job",
    )
    course_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Course or event name printed on the certificate",
    )
    organization_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Organization issuing the certificate",
    )
    issue_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        doc="Date of issue (e.g. 2026-10-08)",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=JobStatus.PENDING.value,
        index=True,
        nullable=False,
        doc="Current job status (PENDING, PROCESSING, COMPLETED, etc.)",
    )
    total_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Total number of recipient rows submitted in the job",
    )
    success_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Count of successfully generated certificates",
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Count of failed recipient items",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Timestamp when the job was accepted by the API",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the background worker began processing",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when all recipients finished processing",
    )

    # 1-to-many relationship with cascading delete
    certificates: Mapped[List["Certificate"]] = relationship(
        "Certificate",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Certificate.position",
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id} status={self.status} total={self.total_count}>"


class Certificate(Base):
    """
    Represents an individual certificate row for a specific recipient.
    Contains recipient details, processing state, error explanation (if any), and file path.
    """
    __tablename__ = "certificates"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the individual certificate",
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Foreign key pointing to the parent Job",
    )
    position: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="0-based index of recipient in the original request for deterministic ordering",
    )
    recipient_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Full name of recipient as submitted in the request",
    )
    recipient_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Email address of recipient as submitted in the request",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=CertificateStatus.PENDING.value,
        index=True,
        nullable=False,
        doc="Status of this individual certificate item (PENDING, PROCESSING, SUCCESS, FAILED)",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Explanation if recipient validation or PDF rendering failed",
    )
    file_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="Filesystem path where the generated PDF is saved",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Timestamp when recipient row was created",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when generation finished or failed",
    )

    # Many-to-1 relationship back to the parent Job
    job: Mapped["Job"] = relationship(
        "Job",
        back_populates="certificates",
    )

    def __repr__(self) -> str:
        return f"<Certificate id={self.id} recipient={self.recipient_name} status={self.status}>"


# Composite index on job_id and status to speed up queries like:
# GET /jobs/{id}/certificates?status=SUCCESS
Index("ix_certificates_job_id_status", Certificate.job_id, Certificate.status)
