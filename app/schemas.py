import re
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings
from app.models import JobStatus, CertificateStatus

# Regex for recipient email validation during individual item checks
# Used in recipient-level validation (NOT in Pydantic schema to prevent request-level 422)
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class RecipientInput(BaseModel):
    """
    Individual recipient payload submitted in a bulk job creation request.
    IMPORTANT DESIGN DECISION:
    Both `name` and `email` are typed as Optional[Any].
    This ensures FastAPI's Pydantic validation tier will NOT reject the entire bulk request (422)
    if one recipient has a malformed email, empty name, None, or non-string data.
    Validation is handled manually at the recipient level inside `job_service.py`.
    """
    name: Optional[Any] = Field(default=None, description="Recipient's full name")
    email: Optional[Any] = Field(default=None, description="Recipient's email address")
    extra: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional additional metadata or custom fields"
    )

    model_config = ConfigDict(extra="ignore")


class JobCreateRequest(BaseModel):
    """
    Payload for creating a new bulk certificate generation job.
    Enforces Request-Level (Tier 1) validation rules:
    - course_name must not be empty or whitespace-only
    - organization_name must not be empty or whitespace-only
    - issue_date must be a valid ISO date (e.g. '2026-10-08')
    - recipients list must not be empty and must not exceed MAX_RECIPIENTS
    """
    course_name: str = Field(..., min_length=1, max_length=255, description="Course or event title")
    organization_name: str = Field(..., min_length=1, max_length=255, description="Issuing organization")
    issue_date: date = Field(..., description="Date of issue, e.g. '2026-10-08'")
    recipients: List[RecipientInput] = Field(
        ...,
        description="List of recipients to generate certificates for"
    )

    @field_validator("course_name", "organization_name")
    @classmethod
    def validate_non_whitespace(cls, value: str, info) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError(f"'{info.field_name}' cannot be empty or whitespace only")
        return trimmed

    @field_validator("recipients")
    @classmethod
    def validate_recipients_list(cls, value: List[RecipientInput]) -> List[RecipientInput]:
        settings = get_settings()
        if not value or len(value) == 0:
            raise ValueError("The 'recipients' list cannot be empty")
        if len(value) > settings.max_recipients:
            raise ValueError(
                f"The 'recipients' list cannot exceed {settings.max_recipients} items "
                f"(received {len(value)})"
            )
        return value


class JobCreateResponse(BaseModel):
    """
    HTTP 202 Accepted response returned immediately when a bulk job is submitted.
    Gives the client the job_id and HATEOAS-style links to monitor and download certificates.
    """
    job_id: uuid.UUID
    status: JobStatus
    total_count: int
    message: str = "Job accepted and queued for background processing"
    links: Dict[str, str]

    model_config = ConfigDict(from_attributes=True)


class CertificateItemResponse(BaseModel):
    """
    Detailed information for an individual recipient's certificate.
    """
    id: uuid.UUID
    position: int = Field(default=0, description="0-based index in the original request")
    recipient_name: str
    recipient_email: str
    status: CertificateStatus
    error_message: Optional[str] = None
    download_url: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class JobStatusResponse(BaseModel):
    """
    Comprehensive job status and progress response for GET /api/v1/jobs/{job_id}.
    Includes real-time counters, completion percentage, and paginated recipient items.
    """
    job_id: uuid.UUID
    course_name: str
    organization_name: str
    issue_date: date
    status: JobStatus
    total_count: int
    success_count: int
    failed_count: int
    pending_count: int
    progress_percentage: float
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    page: int
    page_size: int
    total_pages: int
    recipients: List[CertificateItemResponse]
    links: Dict[str, str]

    model_config = ConfigDict(from_attributes=True)


class CertificateListResponse(BaseModel):
    """
    Paginated list of certificates for GET /api/v1/jobs/{job_id}/certificates.
    Can be filtered by ?status=SUCCESS|FAILED|PENDING|PROCESSING.
    """
    job_id: uuid.UUID
    total: int
    page: int
    page_size: int
    total_pages: int
    items: List[CertificateItemResponse]

    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    """
    Consistent JSON error structure across all API endpoints.
    """
    detail: str
    code: Optional[str] = None
