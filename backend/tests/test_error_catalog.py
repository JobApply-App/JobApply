"""
Every error the API returns carries a code the UI can explain
(backend/core/errors.py ↔ frontend lib/errors.ts + locales errors.codes).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.core.errors import CODES, AppError, install_error_handlers

ROOT = Path(__file__).resolve().parents[2]
_BROWSER_ONLY = {"network", "timeout", "stream_interrupted", "unknown"}


def _frontend_codes() -> set[str]:
    src = (ROOT / "frontend/src/locales/types.ts").read_text(encoding="utf-8")
    block = re.search(r"ERROR_CODES = \[(.*?)\] as const", src, re.S)
    assert block, "ERROR_CODES not found in locales/types.ts — the check would pass vacuously"
    return set(re.findall(r"'([a-z_]+)'", block.group(1)))


def test_backend_and_frontend_catalogs_match():
    front = _frontend_codes()
    assert front - _BROWSER_ONLY == set(CODES), (
        f"only backend: {set(CODES) - front}; only frontend: {front - _BROWSER_ONLY - set(CODES)}"
    )


def test_every_app_error_uses_a_catalog_code():
    files = [f for f in subprocess.check_output(["git", "ls-files", "backend"], cwd=ROOT, text=True).split()
             if f.endswith(".py") and "/tests/" not in f]
    seen = 0
    for f in files:
        tree = ast.parse((ROOT / f).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "AppError":
                seen += 1
                code = n.args[0].value if n.args and isinstance(n.args[0], ast.Constant) else None
                assert code in CODES, f"{f}:{n.lineno} AppError code {code!r} is not in CODES"
    assert seen > 50, f"only {seen} AppError calls found — is the scan looking in the right place?"


def test_unknown_code_is_rejected():
    try:
        AppError("not_a_code")
    except ValueError:
        return
    raise AssertionError("AppError accepted an unknown code")


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    class Body(BaseModel):
        n: int

    @app.get("/app-error")
    def _a():
        raise AppError("daily_cv_limit", detail="limit", limit=20)

    @app.get("/plain")
    def _p():
        raise HTTPException(status_code=404, detail="gone")

    @app.get("/auth")
    def _h():
        raise AppError("session_expired", detail="x", headers={"WWW-Authenticate": "Bearer"})

    @app.post("/validate")
    def _v(body: Body):
        return body

    return TestClient(app)


def test_app_error_body_has_code_and_params():
    r = _client().get("/app-error")
    assert r.status_code == 429
    assert r.json() == {"detail": "limit", "code": "daily_cv_limit", "params": {"limit": 20}}


def test_plain_http_exception_gets_a_status_code():
    r = _client().get("/plain")
    assert r.status_code == 404 and r.json()["code"] == "item_not_found"


def test_headers_survive():
    r = _client().get("/auth")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_validation_error_is_coded():
    r = _client().post("/validate", json={"n": "x"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_input"
