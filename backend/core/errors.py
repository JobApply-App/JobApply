"""
User-facing error codes — one catalog for every error the API returns.

Why
---
Errors used to reach the user as whatever English string the raising line
happened to write: "Scrape Failed: RapidAPI found no LinkedIn job matching
ID ... (outside the 6m lookup window ...)" on a Hebrew page, or a bare
"something went wrong" that explained nothing. Now every error response
carries a stable `code`; the frontend (lib/errors.ts + locales `errors.*`)
turns it into "what happened / why / what to do" in the user's language.
`detail` stays an English fallback for logs, scripts and old clients.

Response shape (every HTTPException, via main.py's handler):

    {"detail": "<English fallback>", "code": "<code>", "params": {...}}

Raise AppError for anything a user can see. A plain HTTPException still
gets a code — inferred from its status (STATUS_FALLBACK) — so nothing ever
reaches the UI uncoded; docs/error-catalog.md lists every code and the text
each language shows.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

# code -> default HTTP status. The frontend owns the wording; this list is
# the contract (test_error_catalog.py keeps it in sync with the locales).
CODES: dict[str, int] = {
    # Session & access
    "auth_required":           401,
    "session_expired":         401,
    "forbidden":               403,
    "admin_only":              403,
    "dev_only":                403,
    "auth_not_configured":     503,
    # Limits
    "rate_limited":            429,
    "daily_cv_limit":          429,
    "daily_chat_limit":        429,
    "linkedin_quota":          429,
    # Not found
    "job_not_found":           404,
    "application_not_found":   404,
    "session_not_found":       404,
    "item_not_found":          404,
    "task_expired":            404,
    # Input
    "invalid_input":           422,
    "empty_message":           422,
    "invalid_linkedin_url":    422,
    "file_too_large":          413,
    "unsupported_file":        415,
    "legacy_doc":              415,
    "file_mismatch":           422,
    "conflict":                409,
    # Analysing a job link
    "posting_closed":          410,
    "linkedin_login_wall":     422,
    "linkedin_blocked":        422,
    "linkedin_job_not_found":  422,
    "linkedin_unavailable":    503,
    "scrape_failed":           422,
    "scrape_empty":            422,
    "job_no_description":      400,
    "job_no_url":              422,
    "analysis_failed":         502,
    # AI features
    "ai_unavailable":          503,
    "ai_failed":               502,
    "ai_bad_output":           502,
    # Documents
    "pdf_unavailable":         503,
    "pdf_failed":              502,
    # Generic
    "service_unavailable":     503,
    "server_error":            500,
}

# A plain HTTPException (no AppError) still gets a code from its status.
STATUS_FALLBACK: dict[int, str] = {
    400: "invalid_input",
    401: "session_expired",
    403: "forbidden",
    404: "item_not_found",
    409: "conflict",
    410: "posting_closed",
    413: "file_too_large",
    415: "unsupported_file",
    422: "invalid_input",
    429: "rate_limited",
    502: "ai_failed",
    503: "service_unavailable",
    504: "service_unavailable",
}


def code_for_status(status: int) -> str:
    return STATUS_FALLBACK.get(status, "server_error" if status >= 500 else "invalid_input")


class AppError(HTTPException):
    """
    An HTTPException with a catalog code and optional params for the UI
    message (e.g. limit=20, feature="cv_tailoring").

        raise AppError("job_not_found", detail=f"Job {job_id!r} not found.")
        raise AppError("ai_failed", 502, "CV tailoring failed.", feature="cv_tailoring")
    """

    def __init__(
        self,
        code: str,
        status_code: Optional[int] = None,
        detail: str = "",
        *,
        headers: Optional[dict[str, str]] = None,
        **params: Any,
    ) -> None:
        if code not in CODES:
            raise ValueError(f"unknown error code {code!r} — add it to backend/core/errors.py CODES")
        super().__init__(status_code=status_code or CODES[code], detail=detail or code, headers=headers)
        self.code = code
        self.params = params


def error_body(exc: HTTPException) -> dict[str, Any]:
    """The JSON body for any HTTPException — always with a code."""
    detail = exc.detail
    code = getattr(exc, "code", None)
    # profile.py's CV-upload errors already send {"code", "message"} as detail.
    if code is None and isinstance(detail, dict) and isinstance(detail.get("code"), str):
        code = detail["code"]
    body: dict[str, Any] = {"detail": detail, "code": code or code_for_status(exc.status_code)}
    params = getattr(exc, "params", None)
    if params:
        body["params"] = params
    return body


def install_error_handlers(app) -> None:
    """Make every HTTPException and validation error response carry a code."""
    from fastapi import Request
    from fastapi.encoders import jsonable_encoder
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=error_body(exc), headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"detail": jsonable_encoder(exc.errors()), "code": "invalid_input"},
        )
