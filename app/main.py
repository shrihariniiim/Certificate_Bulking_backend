import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.models import Job
from app.routers import certificates, jobs
from app.services.job_service import recover_stale_jobs

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    - Creates database tables on startup.
    - Recovers any stale jobs left in PROCESSING state from previous server runs.
    """
    # 1. Ensure all database tables exist
    Base.metadata.create_all(bind=engine)

    # 2. Startup recovery: mark stale PROCESSING jobs as FAILED (Rule 8)
    recover_stale_jobs()

    yield


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description=(
        "Production-quality Bulk Certificate Generator API. "
        "Accepts bulk recipient requests, asynchronously generates elegant PDF certificates "
        "from a predefined template, tracks progress live, and serves single PDFs and ZIP bundles."
    ),
    lifespan=lifespan,
)

# Unified error handler for standard HTTPExceptions (404, 409, etc.)
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# Unified error handler for RequestValidationError (422) guaranteeing identical {"detail": ...} shape
@app.exception_handler(RequestValidationError)
async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
    error_messages = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "Validation error")
        error_messages.append(f"{loc}: {msg}")
    combined_detail = "; ".join(error_messages) if error_messages else "Request validation failed"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": combined_detail},
    )


# Catch-all Exception handler returning {"detail": "Internal server error"} and logging traceback
@app.exception_handler(Exception)
async def custom_unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled server exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# Register routers
app.include_router(jobs.router)
app.include_router(certificates.router)


@app.get(
    "/health",
    tags=["System"],
    summary="Health check",
    description="Returns the health status of the API and validates database connectivity.",
)
def health_check(response: Response, db: Session = Depends(get_db)):
    """
    Health check endpoint (located in main.py per Rule 4).
    Validates database connectivity; returns HTTP 503 if disconnected.
    """
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": "connected",
            "version": settings.app_version,
        }
    except Exception as e:
        logger.error(f"Health check database error: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "version": settings.app_version,
            },
        )


@app.get(
    "/",
    tags=["System"],
    summary="Root API info",
    include_in_schema=False,
)
def root():
    return {
        "title": settings.app_title,
        "version": settings.app_version,
        "docs_url": "/docs",
        "health_url": "/health",
        "api_prefix": "/api/v1",
    }
