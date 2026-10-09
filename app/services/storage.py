import io
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import List, Tuple

from app.config import get_settings


def sanitize_filename(name: str) -> str:
    """
    Sanitizes a string to be safely used as a filename component.
    Removes dangerous characters like slashes, backslashes, colons, null bytes,
    while preserving Unicode letters and numbers.
    """
    # Replace slashes and path traversal tokens with underscore
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', name.strip())
    # Collapse multiple consecutive underscores or spaces
    cleaned = re.sub(r'[\s_]+', '_', cleaned)
    # Trim leading/trailing underscores and dots
    cleaned = cleaned.strip('_. ')
    return cleaned[:50] or "recipient"


class StorageService:
    """
    Manages reading and writing certificate PDF files on disk and assembling ZIP bundles.
    Enforces security best practices:
    - Files are named using only {certificate_id}.pdf
    - Atomic writes using temporary file + rename to prevent corrupt/partial reads
    - Strict path resolution to prevent directory traversal attacks
    """

    def __init__(self, base_dir: Path | str | None = None):
        if base_dir is None:
            self.base_dir = get_settings().resolved_storage_path
        else:
            self.base_dir = Path(base_dir).resolve()
            self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_certificate_pdf(self, certificate_id: uuid.UUID | str, pdf_bytes: bytes) -> str:
        """
        Atomically saves PDF bytes to disk under {certificate_id}.pdf.
        Uses a temporary file in the same directory and renames it atomically.
        Returns the relative filename to store in the database.
        """
        cert_id_str = str(certificate_id)
        final_filename = f"{cert_id_str}.pdf"
        final_path = self.base_dir / final_filename

        # Write to temporary file first in the same directory
        temp_path = self.base_dir / f"{cert_id_str}.tmp"
        try:
            with open(temp_path, "wb") as f:
                f.write(pdf_bytes)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is flushed to physical disk

            # Atomic replace (works atomically on POSIX and modern Windows on the same filesystem)
            os.replace(temp_path, final_path)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

        # Return relative path to keep database records location-agnostic
        return final_filename

    def resolve_path(self, relative_path: str) -> Path:
        """
        Resolves a relative file path and verifies it strictly resides within self.base_dir.
        Raises ValueError if directory traversal is attempted.
        Raises FileNotFoundError if the file does not exist on disk.
        """
        # Strip leading slashes to prevent absolute path escapes
        safe_rel = relative_path.lstrip("/\\")
        candidate = (self.base_dir / safe_rel).resolve()

        # Strict containment check
        try:
            candidate.relative_to(self.base_dir)
        except ValueError:
            raise ValueError(f"Security error: path '{relative_path}' escapes storage directory")

        if not candidate.is_file():
            raise FileNotFoundError(f"Certificate file not found: {relative_path}")

        return candidate

    def read_certificate_pdf(self, relative_path: str) -> bytes:
        """Reads and returns the raw PDF bytes of a saved certificate."""
        file_path = self.resolve_path(relative_path)
        return file_path.read_bytes()

    def build_certificates_zip(self, items: List[Tuple[str, str, uuid.UUID | str]]) -> bytes:
        """
        Assembles an in-memory ZIP archive containing the provided certificates.
        items: List of tuples (recipient_name, relative_path, certificate_id)
        Files inside the ZIP are named safely as:
        {sanitized_recipient_name}_{short_id}.pdf
        This guarantees collision-free, human-readable file names inside the archive.
        """
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for recipient_name, rel_path, cert_id in items:
                if not rel_path:
                    continue

                try:
                    file_path = self.resolve_path(rel_path)
                except (FileNotFoundError, ValueError):
                    continue

                safe_name = sanitize_filename(recipient_name)
                short_id = str(cert_id)[:8]
                archive_filename = f"{safe_name}_{short_id}.pdf"

                # Read and add to ZIP
                zip_file.writestr(archive_filename, file_path.read_bytes())

        zip_buffer.seek(0)
        return zip_buffer.getvalue()


# Default singleton instance
default_storage = StorageService()
