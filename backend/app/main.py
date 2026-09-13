import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, attachments, auth, reporting, routes, tickets
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.audit import request_context

logging.basicConfig(format="%(message)s", level=logging.INFO)
app = FastAPI(
    title="Samsung D2C Service Desk",
    version="2.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "Authorization"],
)


def error(code, message, status):
    return JSONResponse(
        {"success": False, "error": {"code": code, "message": message}},
        status_code=status,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return error(
        {
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
        }.get(exc.status_code, "REQUEST_ERROR"),
        str(exc.detail),
        exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error(
        "VALIDATION_ERROR",
        "; ".join(".".join(str(x) for x in e["loc"][1:]) + ": " + e["msg"] for e in exc.errors()),
        422,
    )


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return error("CONFLICT", "This operation conflicts with an existing record or reference", 409)


@app.middleware("http")
async def request_metadata(request: Request, call_next):
    rid = str(uuid.uuid4())
    token = request_context.set(
        {
            "request_id": rid,
            "ip_address": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent", "")[:512],
        }
    )
    try:
        response = None
        length = request.headers.get("content-length")
        if length and (
            not length.isdigit() or int(length) > settings.max_upload_bytes + 1024 * 1024
        ):
            response = error("PAYLOAD_TOO_LARGE", "Request exceeds upload limit", 413)
        if request.url.path == "/api/v1/auth/login":
            origin = request.headers.get("origin")
            if (
                origin
                and origin not in settings.cors_origins.split(",")
                and origin != str(request.base_url).rstrip("/")
            ):
                response = error("FORBIDDEN", "Untrusted origin", 403)
        if response is None:
            response = await call_next(request)
    except Exception as exc:
        logging.error(
            json.dumps(
                {
                    "event": "request_failed",
                    "error_type": type(exc).__name__,
                    "request_id": rid,
                    "path": request.url.path,
                }
            )
        )
        response = error(
            "INTERNAL_ERROR",
            "An unexpected error occurred. Contact IT with the request ID.",
            500,
        )
    finally:
        request_context.reset(token)
    response.headers.update(
        {
            "X-Request-ID": rid,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "same-origin",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        }
    )
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if response.status_code >= 400:
        logging.warning(
            json.dumps(
                {
                    "event": "api_error",
                    "request_id": rid,
                    "status": response.status_code,
                    "path": request.url.path,
                }
            )
        )
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return error("NOT_READY", "Database unavailable", 503)


for router in (
    auth.router,
    tickets.router,
    admin.router,
    reporting.router,
    attachments.router,
    routes.router,
):
    app.include_router(router, prefix="/api/v1")
docs_assets = Path(__file__).resolve().parent / "static"


@app.get("/api/docs", include_in_schema=False)
def api_docs():
    return FileResponse(docs_assets / "index.html")


app.mount("/api/docs-assets", StaticFiles(directory=docs_assets), name="docs-assets")
frontend = Path(__file__).resolve().parents[2] / "frontend"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
