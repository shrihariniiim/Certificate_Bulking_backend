import io
import uuid
from datetime import date
from pathlib import Path
from typing import Union

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Cache flag to ensure fonts are registered only once per Python process
_FONTS_REGISTERED = False

# Font directory resolved relative to this module file
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def register_fonts_once() -> None:
    """
    Registers Unicode TrueType fonts (NotoSans, NotoSansTamil, NotoSansDevanagari).
    Executed once per process to support multilingual recipient names and characters.
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return

    # Map of logical font name -> filename
    font_files = {
        "NotoSans": "NotoSans-Regular.ttf",
        "NotoSansTamil": "NotoSansTamil-Regular.ttf",
        "NotoSansDevanagari": "NotoSansDevanagari-Regular.ttf",
    }

    for font_name, filename in font_files.items():
        font_path = FONTS_DIR / filename
        if font_path.is_file():
            # Only register if not already known by ReportLab
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    _FONTS_REGISTERED = True


def select_font_for_text(text: str) -> str:
    """
    Selects the optimal registered font based on Unicode character ranges.
    - Tamil: U+0B80 to U+0BFF -> NotoSansTamil
    - Devanagari (Hindi, Marathi, Sanskrit): U+0900 to U+097F -> NotoSansDevanagari
    - Latin / Default: -> NotoSans (falls back to Helvetica if font missing)
    """
    register_fonts_once()
    registered = pdfmetrics.getRegisteredFontNames()

    for ch in text:
        code = ord(ch)
        if 0x0B80 <= code <= 0x0BFF and "NotoSansTamil" in registered:
            return "NotoSansTamil"
        if 0x0900 <= code <= 0x097F and "NotoSansDevanagari" in registered:
            return "NotoSansDevanagari"

    return "NotoSans" if "NotoSans" in registered else "Helvetica"


def auto_shrink_font_size(
    text: str,
    font_name: str,
    max_size: float = 30.0,
    min_size: float = 12.0,
    max_width_pt: float = 620.0,
) -> float:
    """
    Calculates the largest font size (between max_size and min_size)
    such that the rendered text fits within max_width_pt without clipping.
    Uses ReportLab's exact stringWidth measurement.
    """
    size = max_size
    while size > min_size:
        rendered_width = pdfmetrics.stringWidth(text, font_name, size)
        if rendered_width <= max_width_pt:
            return size
        size -= 0.5
    return min_size


def generate_certificate_pdf(
    recipient_name: str,
    course_name: str,
    organization_name: str,
    issue_date: Union[date, str],
    certificate_id: Union[uuid.UUID, str],
) -> bytes:
    """
    Pure certificate generation function:
    - Accepts plain data values (no DB models or ORM dependencies).
    - Renders a single predefined, high-quality landscape certificate template.
    - Zero file or DB I/O: returns pure PDF bytes from an in-memory buffer.
    """
    register_fonts_once()

    # Create in-memory buffer
    buffer = io.BytesIO()

    # Landscape letter format (792 x 612 pt)
    page_width, page_height = landscape(letter)
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    c.setTitle(f"Certificate - {recipient_name}")

    # Palette
    c_primary = HexColor("#1A365D")    # Deep corporate navy
    c_gold = HexColor("#C59B27")       # Elegant metallic gold
    c_dark = HexColor("#2D3748")       # Charcoal for body text
    c_muted = HexColor("#718096")      # Light gray for IDs/subtitles
    c_bg_accent = HexColor("#F7FAFC")  # Subtle background fill

    # 1. Background subtle fill
    c.setFillColor(c_bg_accent)
    c.rect(0, 0, page_width, page_height, stroke=0, fill=1)

    # 2. Outer and inner border framing
    margin = 28
    c.setStrokeColor(c_primary)
    c.setLineWidth(3.5)
    c.rect(margin, margin, page_width - (margin * 2), page_height - (margin * 2))

    inner_margin = margin + 7
    c.setStrokeColor(c_gold)
    c.setLineWidth(1.2)
    c.rect(inner_margin, inner_margin, page_width - (inner_margin * 2), page_height - (inner_margin * 2))

    # Corner decorative squares
    corner_size = 10
    c.setFillColor(c_gold)
    c.rect(inner_margin, inner_margin, corner_size, corner_size, stroke=0, fill=1)
    c.rect(page_width - inner_margin - corner_size, inner_margin, corner_size, corner_size, stroke=0, fill=1)
    c.rect(inner_margin, page_height - inner_margin - corner_size, corner_size, corner_size, stroke=0, fill=1)
    c.rect(page_width - inner_margin - corner_size, page_height - inner_margin - corner_size, corner_size, corner_size, stroke=0, fill=1)

    # 3. Organization Header (Top)
    org_font = select_font_for_text(organization_name)
    c.setFont(org_font, 14)
    c.setFillColor(c_primary)
    c.drawCentredString(page_width / 2, page_height - 90, organization_name.upper())

    # Gold divider bar below org name
    c.setStrokeColor(c_gold)
    c.setLineWidth(1.5)
    c.line((page_width / 2) - 80, page_height - 100, (page_width / 2) + 80, page_height - 100)

    # 4. Title: "CERTIFICATE OF COMPLETION"
    title_font = select_font_for_text("CERTIFICATE OF COMPLETION")
    c.setFont(title_font, 26)
    c.setFillColor(c_primary)
    c.drawCentredString(page_width / 2, page_height - 145, "CERTIFICATE OF COMPLETION")

    # 5. Subtitle: Presentation text
    sub_font = select_font_for_text("This is proudly presented to")
    c.setFont(sub_font, 11)
    c.setFillColor(c_muted)
    c.drawCentredString(page_width / 2, page_height - 180, "THIS IS PROUDLY PRESENTED TO")

    # 6. Recipient Name with dynamic Unicode font and auto-shrinking
    name_font = select_font_for_text(recipient_name)
    name_size = auto_shrink_font_size(
        text=recipient_name,
        font_name=name_font,
        max_size=32.0,
        min_size=12.0,
        max_width_pt=page_width - 160,
    )
    c.setFont(name_font, name_size)
    c.setFillColor(c_primary)
    c.drawCentredString(page_width / 2, page_height - 240, recipient_name)

    # Gold decorative underline under recipient name
    name_width = min(pdfmetrics.stringWidth(recipient_name, name_font, name_size), page_width - 160)
    line_half = max(name_width / 2 + 20, 100)
    c.setStrokeColor(c_gold)
    c.setLineWidth(1.2)
    c.line((page_width / 2) - line_half, page_height - 252, (page_width / 2) + line_half, page_height - 252)

    # 7. Course completion description
    desc_font = select_font_for_text("for successfully completing the course")
    c.setFont(desc_font, 11)
    c.setFillColor(c_dark)
    c.drawCentredString(page_width / 2, page_height - 290, "for successfully completing the training program on")

    # 8. Course / Event Name
    course_font = select_font_for_text(course_name)
    course_size = auto_shrink_font_size(
        text=course_name,
        font_name=course_font,
        max_size=20.0,
        min_size=11.0,
        max_width_pt=page_width - 160,
    )
    c.setFont(course_font, course_size)
    c.setFillColor(c_primary)
    c.drawCentredString(page_width / 2, page_height - 330, course_name)

    # 9. Footer: Date, Certificate ID, and Signature Line
    footer_y = 120
    date_str = str(issue_date)

    # Left: Issue Date
    c.setFont(select_font_for_text(date_str), 11)
    c.setFillColor(c_dark)
    c.drawString(inner_margin + 40, footer_y, date_str)
    c.setStrokeColor(c_muted)
    c.setLineWidth(0.8)
    c.line(inner_margin + 40, footer_y - 8, inner_margin + 180, footer_y - 8)
    c.setFont(select_font_for_text("Date of Issue"), 9)
    c.setFillColor(c_muted)
    c.drawString(inner_margin + 40, footer_y - 22, "Date of Issue")

    # Right: Authorized Signatory
    c.setFont(org_font, 11)
    c.setFillColor(c_dark)
    c.drawRightString(page_width - inner_margin - 40, footer_y, organization_name)
    c.line(page_width - inner_margin - 180, footer_y - 8, page_width - inner_margin - 40, footer_y - 8)
    c.setFont(select_font_for_text("Authorized Signatory"), 9)
    c.setFillColor(c_muted)
    c.drawRightString(page_width - inner_margin - 40, footer_y - 22, "Authorized Signatory")

    # Center bottom: Certificate ID for verification
    cert_id_str = f"Certificate ID: {certificate_id}"
    c.setFont(select_font_for_text(cert_id_str), 8)
    c.setFillColor(c_muted)
    c.drawCentredString(page_width / 2, inner_margin + 20, cert_id_str)

    # Finalize PDF page
    c.showPage()
    c.save()

    buffer.seek(0)
    return buffer.getvalue()
