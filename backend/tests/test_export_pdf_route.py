"""
POST /api/resumes/export-pdf — binary PDF download.

The preview embeds the CV as a data: URI with `#toolbar=0`, which suppresses
the browser's own PDF chrome — including its download button. Until this
endpoint existed there was no way for a user to actually get their CV out of
the app. These tests cover the delivery contract that makes the download work:
correct headers, real PDF bytes, and a filename that survives a Hebrew name.

build_pdf is stubbed. Launching real Chromium per test would make these slow
and dependent on a browser being installed, and what is under test here is the
HTTP delivery layer, not the renderer (covered by the pdf_builder tests).
"""
from __future__ import annotations

import re
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

import backend.api.routes.resumes as resumes_mod
from backend.api.deps import CurrentUser, get_current_user
from backend.main import app

_FAKE_PDF = b"%PDF-1.4\n%fake-but-well-formed\n%%EOF\n"


@pytest.fixture()
def client(monkeypatch):
    """Per-test auth override — set up and torn down around each test, for the
    reason documented in test_linkedin_jobs_route.py's identical fixture."""
    async def _fake_build_pdf(cv_data, output_path=None, template_id=None, *, user_id):
        return _FAKE_PDF

    monkeypatch.setattr(resumes_mod, "build_pdf", _fake_build_pdf)

    def _override_user():
        return CurrentUser(user_id="test-user", email="test@example.com")

    app.dependency_overrides[get_current_user] = _override_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _post(client, cv_data=None, template_id="t2_modern"):
    return client.post("/api/resumes/export-pdf", json={
        "cv_data": cv_data if cv_data is not None else {"header": {"target_title": "PM"}},
        "template_id": template_id,
    })


# ── Delivery contract ────────────────────────────────────────────────────────

def test_returns_raw_pdf_bytes_not_base64(client):
    res = _post(client)
    assert res.status_code == 200
    assert res.content == _FAKE_PDF
    assert res.content.startswith(b"%PDF-")


def test_content_type_is_application_pdf(client):
    res = _post(client)
    assert res.headers["content-type"] == "application/pdf"


def test_content_disposition_forces_a_download(client):
    """`attachment` is what makes this a download rather than a navigation —
    without it the browser opens a viewer tab and the 1-click flow is gone."""
    res = _post(client)
    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert ".pdf" in disposition


def test_content_length_matches_the_payload(client):
    res = _post(client)
    assert int(res.headers["content-length"]) == len(_FAKE_PDF)


def test_response_is_not_cached(client):
    """The CV is per-user and regenerated on every edit; a cached copy would
    hand the user last week's document after they changed it."""
    res = _post(client)
    assert res.headers.get("cache-control") == "no-store"


# ── Filename derivation ──────────────────────────────────────────────────────

def test_filename_uses_the_profile_name(client, monkeypatch):
    monkeypatch.setattr(resumes_mod, "get_profile",
                        lambda uid: {"personal": {"name": "Ron Morim"}})
    disposition = _post(client).headers["content-disposition"]
    assert 'filename="Ron_Morim_CV.pdf"' in disposition


def test_hebrew_name_does_not_break_the_header(client, monkeypatch):
    """
    Content-Disposition is latin-1. A naive f-string with a Hebrew name raises
    UnicodeEncodeError at response time — the download fails for exactly the
    users this product is built for. RFC 5987's filename*= carries the real
    name; the ASCII filename= stays as a fallback.
    """
    monkeypatch.setattr(resumes_mod, "get_profile",
                        lambda uid: {"personal": {"name": "רון מורים"}})
    res = _post(client)
    assert res.status_code == 200

    disposition = res.headers["content-disposition"]
    # ASCII fallback must still be present and safe
    plain = re.search(r'filename="([^"]+)"', disposition)
    assert plain and plain.group(1).endswith(".pdf")
    assert plain.group(1).isascii()

    # and the real name is recoverable from filename*
    star = re.search(r"filename\*=UTF-8''([^;]+)", disposition)
    assert star, disposition
    assert "רון" in unquote(star.group(1))


def test_missing_profile_name_falls_back_to_a_generic_filename(client, monkeypatch):
    monkeypatch.setattr(resumes_mod, "get_profile", lambda uid: {"personal": {}})
    assert 'filename="CV.pdf"' in _post(client).headers["content-disposition"]


def test_profile_lookup_failure_does_not_break_the_download(client, monkeypatch):
    """A filename is cosmetic; losing the CV over it would not be."""
    def _boom(uid):
        raise RuntimeError("profile store unavailable")
    monkeypatch.setattr(resumes_mod, "get_profile", _boom)
    res = _post(client)
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


# ── CV shape handling ────────────────────────────────────────────────────────

def test_legacy_cv_shape_is_accepted(client):
    """Stored CVs predate the schema unification; they must still export."""
    res = _post(client, cv_data={
        "title": "Customer Success Manager",
        "military": {"role": "Staff Officer", "unit": "IDF", "dates": "2017 - 2019"},
        "experience": [{"role": "CSM", "company": "Acme", "bullets": ["Did X."]}],
    })
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_canonical_cv_shape_is_accepted(client):
    res = _post(client, cv_data={
        "header": {"target_title": "Head of Product"},
        "military_service": {"role_title": "Ops NCO", "unit_type": "IDF Logistics",
                             "dates": "2016 - 2018", "key_responsibilities": ["Ran resupply."]},
        "experience": [{"role": "PM", "company": "Globex", "bullets": ["Shipped X."]}],
    })
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_empty_cv_still_produces_a_document(client):
    """An empty draft should export a blank CV, not a 500."""
    res = _post(client, cv_data={})
    assert res.status_code == 200


# ── Failure surfaces ─────────────────────────────────────────────────────────

def test_missing_browser_reports_the_honest_503(client, monkeypatch):
    """
    Reuses the shared _pdf_http_error mapping: a missing Chromium is permanent,
    so the client must not be told to retry.
    """
    from backend.services.pdf_builder import PdfEngineUnavailable

    async def _no_browser(*a, **k):
        raise PdfEngineUnavailable("Chromium is not installed")
    monkeypatch.setattr(resumes_mod, "build_pdf", _no_browser)

    res = _post(client)
    assert res.status_code == 503
    assert "not something retrying will fix" in res.json()["detail"]


def test_transient_render_failure_is_a_502(client, monkeypatch):
    async def _boom(*a, **k):
        raise TimeoutError("page.pdf timed out")
    monkeypatch.setattr(resumes_mod, "build_pdf", _boom)

    res = _post(client)
    assert res.status_code == 502
    assert "try again" in res.json()["detail"].lower()


def test_endpoint_requires_authentication():
    """No override installed — the route must not be anonymously reachable."""
    assert get_current_user not in app.dependency_overrides
    anon = TestClient(app)
    res = anon.post("/api/resumes/export-pdf",
                    json={"cv_data": {}, "template_id": "t2_modern"})
    assert res.status_code in (401, 403)
