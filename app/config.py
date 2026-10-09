from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application runtime configuration loaded from environment variables or .env file.
    Designed using pydantic-settings for strict type checking and default fallbacks.
    """
    # Database connection URL.
    # Default is a local SQLite database stored in the storage directory.
    # To switch to PostgreSQL, only override this variable in .env or the container environment:
    # Example: postgresql+psycopg://postgres:secret@localhost:5432/certificates_db
    database_url: str = "sqlite:///./storage/app.db"

    # Directory path where generated certificate PDFs and temporary ZIP archives will be saved
    storage_dir: str = "./storage/certificates"

    # Maximum number of recipients allowed per single bulk generation request
    # Requests exceeding this count fail at the request-level validation tier (HTTP 422)
    max_recipients: int = 1000

    # Maximum allowed recipient name length before being flagged as FAILED
    max_name_length: int = 100

    # API metadata
    app_title: str = "Bulk Certificate Generator API"
    app_version: str = "1.0.0"

    # Pydantic settings configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def resolved_storage_path(self) -> Path:
        """Returns a resolved Path object for storage_dir, creating it if it doesn't exist."""
        path = Path(self.storage_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    """
    Cached accessor for application settings.
    Using @lru_cache ensures configuration is parsed once per process,
    while still allowing test fixtures to override or clear the cache when needed.
    """
    return Settings()
