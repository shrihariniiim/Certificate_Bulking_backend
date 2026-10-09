import io
import uuid
from datetime import date
from pypdf import PdfReader

from app.services.certificate_generator import (
    generate_certificate_pdf,
    select_font_for_text,
    auto_shrink_font_size,
)


def test_pure_pdf_generation_english():
    """Verifies that generate_certificate_pdf returns valid PDF bytes containing recipient text."""
    cert_id = uuid.uuid4()
    pdf_bytes = generate_certificate_pdf(
        recipient_name="Eleanor Vance",
        course_name="Quantum Computing Intro",
        organization_name="Aereo Institute",
        issue_date=date(2026, 10, 8),
        certificate_id=cert_id,
    )

    # 1. Valid PDF header check
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000

    # 2. Text extraction via pypdf
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    page_text = reader.pages[0].extract_text()

    assert "Eleanor Vance" in page_text
    assert "Quantum Computing Intro" in page_text
    assert "Aereo Institute" in page_text
    assert str(cert_id) in page_text
    assert "CERTIFICATE OF COMPLETION" in page_text


def test_pure_pdf_generation_tamil():
    """Verifies Tamil Unicode text extraction from the generated PDF."""
    cert_id = uuid.uuid4()
    tamil_name = "சுரேஷ் குமார்"
    pdf_bytes = generate_certificate_pdf(
        recipient_name=tamil_name,
        course_name="Machine Learning Bootcamp",
        organization_name="Aereo Academy",
        issue_date=date(2026, 10, 8),
        certificate_id=cert_id,
    )

    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_text = reader.pages[0].extract_text()
    assert tamil_name in page_text


def test_pure_pdf_generation_hindi():
    """Verifies Hindi / Devanagari Unicode text extraction from the generated PDF."""
    cert_id = uuid.uuid4()
    hindi_name = "रोहित शर्मा"
    pdf_bytes = generate_certificate_pdf(
        recipient_name=hindi_name,
        course_name="Web Architecture",
        organization_name="Aereo Academy",
        issue_date=date(2026, 10, 8),
        certificate_id=cert_id,
    )

    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_text = reader.pages[0].extract_text()
    assert hindi_name in page_text


def test_auto_shrink_font_size():
    """Verifies that font size downscales properly for very long strings."""
    font_name = select_font_for_text("Short")
    short_size = auto_shrink_font_size("Short Name", font_name, max_size=30.0, min_size=12.0)
    assert short_size == 30.0

    long_str = "Alexander " * 10
    long_size = auto_shrink_font_size(long_str, font_name, max_size=30.0, min_size=12.0)
    assert long_size < short_size
    assert long_size >= 12.0
