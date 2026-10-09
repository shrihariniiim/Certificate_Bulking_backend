import uuid
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Certificate, CertificateStatus
from app.services.storage import default_storage

router = APIRouter(prefix="/api/v1/certificates", tags=["Certificates"])


@router.get(
    "/{certificate_id}/download",
    summary="Download an individual certificate PDF",
    description=(
        "Downloads a single recipient certificate PDF. "
        "Returns HTTP 404 if not found, or HTTP 409 if generation is still pending or failed."
    ),
)
def download_certificate(
    certificate_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    cert = db.get(Certificate, certificate_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate with ID '{certificate_id}' not found",
        )

    # If certificate is still pending or currently processing
    if cert.status in (CertificateStatus.PENDING.value, CertificateStatus.PROCESSING.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Certificate is currently {cert.status}. Please check back shortly.",
        )

    # If certificate generation failed
    if cert.status == CertificateStatus.FAILED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Certificate generation failed: {cert.error_message or 'Unknown error'}",
        )

    if not cert.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificate file path is not recorded",
        )

    try:
        pdf_bytes = default_storage.read_certificate_pdf(cert.file_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificate PDF file is missing from storage",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{cert.id}.pdf"',
            "Content-Type": "application/pdf",
        },
    )
