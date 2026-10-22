"""
A CV upload must either import a CV or say clearly why it did not.

Testers reported they "couldn't upload a CV". Production logs showed three
distinct ways that happened, none of which told the user anything useful:

1. A Bar Association regulations PDF was uploaded instead of a CV. The LLM
   correctly found nothing, the endpoint returned 200 with zero skills and
   zero experiences, and persisted that empty extraction as the user's
   cv_data — which would have replaced a real CV had there been one.
2. An LLM failure was swallowed inside aggregate_cv_claims() and returned as
   the same empty stub, so "the model was down" and "this is not a CV" were
   indistinguishable — and both overwrote existing data with nothing.
3. Full ingestion takes 20-60s, inside the window in which the Vercel
   gateway drops a proxied request. The backend logged success while the
   browser saw a failure (the same defect /tailor/start fixed for CV
   generation).

These tests pin the replacements: coded errors raised BEFORE anything is
persisted, and an async start/status pair so no request is long-lived.
"""
import asyncio
import io
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser
from backend.api.routes import profile as profile_routes
from backend.core.database import ENGINE
from backend.repositories import profile_repository
from backend.services import cv_aggregator_service as agg

_PDF_BYTES = b"%PDF-1.4\n% fake test pdf\n"

_GOOD_CLAIMS = {
    "personal": {},
    "languages": [],
    "skills": ["SQL"],
    "skill_details": [],
    "domains": [],
    "experiences": [{"company": "Acme", "title": "Analyst", "start": "2020", "end": "2023"}],
    "education": [],
    "summary": "",
}
_EMPTY_CLAIMS = {**_GOOD_CLAIMS, "skills": [], "experiences": []}


def _llm_returning(payload: str):
    async def _fake(**_kwargs):
        return SimpleNamespace(text=payload)
    return _fake


async def _llm_failing(**_kwargs):
    raise RuntimeError("503 from every provider")


def _upload(name: str = "cv.pdf", content: bytes = _PDF_BYTES) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content))


# ── aggregate_cv_claims: failure is not "empty" ──────────────────────────────

async def test_llm_failure_raises_instead_of_returning_empty(monkeypatch):
    monkeypatch.setattr(agg, "call_llm", _llm_failing)
    with pytest.raises(agg.CvAggregationError):
        await agg.aggregate_cv_claims(["some cv text"], user_id="u")


async def test_unparseable_llm_output_raises(monkeypatch):
    monkeypatch.setattr(agg, "call_llm", _llm_returning("sorry, I can't help with that"))
    with pytest.raises(agg.CvAggregationError):
        await agg.aggregate_cv_claims(["some cv text"], user_id="u")


async def test_valid_output_still_parses(monkeypatch):
    monkeypatch.setattr(agg, "call_llm", _llm_returning(json.dumps(_GOOD_CLAIMS)))
    claims = await agg.aggregate_cv_claims(["some cv text"], user_id="u")
    assert claims["skills"] == ["SQL"]
    assert agg.claims_have_cv_content(claims)


def test_empty_extraction_is_not_cv_content():
    assert not agg.claims_have_cv_content(_EMPTY_CLAIMS)
    assert agg.claims_have_cv_content({"education": [{"school": "TAU"}]})


# ── Extraction errors carry a code the UI can translate ──────────────────────

async def test_scanned_pdf_that_ocr_cannot_read_gets_no_text_code(monkeypatch):
    monkeypatch.setattr(agg, "extract_text", lambda content, name: "")

    async def _ocr_nothing(content, fname, user_id):
        return ""
    monkeypatch.setattr(agg, "ocr_pdf", _ocr_nothing)
    with pytest.raises(HTTPException) as exc:
        await profile_routes._extract_cv_texts([_upload()], user_id="u")
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "no_text"


async def test_pdf_without_a_text_layer_is_read_by_ocr(monkeypatch):
    """A scan or a design-tool export used to be rejected as 'scanned image'."""
    monkeypatch.setattr(agg, "extract_text", lambda content, name: "")
    seen = []

    async def _ocr(content, fname, user_id):
        seen.append(fname)
        return "Analyst at Acme 2020-2023, SQL"
    monkeypatch.setattr(agg, "ocr_pdf", _ocr)
    texts, processed, errors, needs_ocr = await profile_routes._extract_cv_texts([_upload()], user_id="u")
    assert texts == ["Analyst at Acme 2020-2023, SQL"] and seen == ["cv.pdf"] and needs_ocr == []


async def test_ocr_is_deferred_to_the_background_task_when_asked(monkeypatch):
    """OCR takes 10-30s — /cv-upload/start must not run it inside the request."""
    monkeypatch.setattr(agg, "extract_text", lambda content, name: "")

    async def _must_not_run(*a, **k):
        raise AssertionError("OCR ran inside the request")
    monkeypatch.setattr(agg, "ocr_pdf", _must_not_run)
    texts, _, _, needs_ocr = await profile_routes._extract_cv_texts([_upload()], user_id="u", defer_ocr=True)
    assert texts == [] and [n for n, _ in needs_ocr] == ["cv.pdf"]


def test_pdf_header_after_leading_bytes_is_still_a_pdf():
    """The spec allows %PDF- anywhere in the first 1 KB; offset 0 was required."""
    assert profile_routes._content_matches_extension(b"\r\n\xef\xbb\xbf%PDF-1.7 ...", "pdf")
    assert not profile_routes._content_matches_extension(b"PK\x03\x04not a pdf", "pdf")


def test_pymupdf_recovers_text_pdfplumber_misses(monkeypatch):
    """Valid PDFs pdfplumber can't read were rejected as 'scanned image'."""
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Senior FP&A Analyst at Acme")
    pdf_bytes = doc.tobytes()

    class _Broken:
        def __enter__(self):
            raise RuntimeError("unsupported font")
        def __exit__(self, *a):
            return False
    monkeypatch.setattr("pdfplumber.open", lambda *a, **k: _Broken())
    assert "FP&A Analyst" in agg._extract_pdf(pdf_bytes)


async def test_wrong_format_gets_unsupported_code():
    with pytest.raises(HTTPException) as exc:
        await profile_routes._extract_cv_texts([_upload("photo.jpg", b"\xff\xd8\xff")], user_id="u")
    assert exc.value.detail["code"] == "unsupported_format"


# ── Ingestion: never overwrite a good CV with nothing ────────────────────────

@pytest.fixture()
def uid(db_available, monkeypatch):
    """A user who already has a good CV on file. Profile JSON kept in memory."""
    u = str(uuid.uuid4())
    store: dict = {}
    # The post-upload matching refresh is covered in test_user_title_terms.py;
    # here it would fire a real LLM call and a catalog scan in the background.
    monkeypatch.setattr(
        "backend.services.all_jobs_match_service.schedule_refresh_for_user", lambda user_id: None
    )
    monkeypatch.setattr(
        "backend.services.user_profile_store.load", lambda user_id: dict(store.get(user_id, {}))
    )
    monkeypatch.setattr(
        "backend.services.user_profile_store.save", lambda user_id, p: store.__setitem__(user_id, p)
    )
    now = datetime.now(timezone.utc).isoformat()
    with Session(ENGINE) as s:
        row, _ = profile_repository.get_or_create(s, u, now=now)
        row.master_profile = {**(row.master_profile or {}), "cv_data": {"skills": ["Existing"]}}
        profile_repository.save(s, row)
        s.commit()
    yield u
    with ENGINE.begin() as c:
        for table in ("confidence_audit_log", "evidence_records", "profile_entities",
                      "cv_documents", "profile_answers", "user_preferences"):
            c.execute(text(f"DELETE FROM public.{table} WHERE user_id = CAST(:u AS uuid)"), {"u": u})
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": u})


def _cv_data(uid: str):
    with Session(ENGINE) as s:
        row, _ = profile_repository.get_or_create(s, uid, now=datetime.now(timezone.utc).isoformat())
        return (row.master_profile or {}).get("cv_data")


def _onboarding_status(uid: str):
    with ENGINE.connect() as c:
        return c.execute(
            text("SELECT onboarding_status FROM public.profiles WHERE id = CAST(:u AS uuid)"),
            {"u": uid},
        ).scalar()


async def test_non_cv_document_is_rejected_and_existing_cv_kept(uid, monkeypatch):
    monkeypatch.setattr(agg, "call_llm", _llm_returning(json.dumps(_EMPTY_CLAIMS)))
    with pytest.raises(HTTPException) as exc:
        await profile_routes._ingest_cv_full(["regulations text"], ["rules.pdf"], [], uid)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "not_a_cv"
    assert _cv_data(uid) == {"skills": ["Existing"]}


async def test_llm_outage_is_503_and_existing_cv_kept(uid, monkeypatch):
    monkeypatch.setattr(agg, "call_llm", _llm_failing)
    with pytest.raises(HTTPException) as exc:
        await profile_routes._ingest_cv_full(["cv text"], ["cv.pdf"], [], uid)
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "llm_unavailable"
    assert _cv_data(uid) == {"skills": ["Existing"]}


# ── Async start/status: the request returns before the LLM finishes ──────────

async def _poll(task_id: str, user: CurrentUser) -> dict:
    for _ in range(500):
        status = await profile_routes.get_cv_upload_status(task_id, user=user)
        if status["status"] != "pending":
            return status
        await asyncio.sleep(0.01)
    raise AssertionError("task never finished")


async def test_start_then_poll_imports_cv_and_opens_pipeline(uid, monkeypatch):
    monkeypatch.setattr(agg, "extract_text", lambda content, name: "Analyst at Acme, SQL")
    monkeypatch.setattr(agg, "call_llm", _llm_returning(json.dumps(_GOOD_CLAIMS)))
    user = CurrentUser(user_id=uid, email="t@example.com")

    started = await profile_routes.start_cv_upload(files=[_upload()], user=user)
    assert started["status"] == "pending"

    done = await _poll(started["task_id"], user)
    assert done["status"] == "done"
    assert done["result"]["cv_claims"]["skills"] == ["SQL"]
    assert _cv_data(uid)["skills"] == ["SQL"]
    # A CV uploaded from any screen admits the user to the matching pipeline.
    assert _onboarding_status(uid) == "complete"


async def test_scanned_pdf_is_ocrd_in_the_background_and_imported(uid, monkeypatch):
    monkeypatch.setattr(agg, "extract_text", lambda content, name: "")

    async def _ocr(content, fname, user_id):
        return "Analyst at Acme, SQL"
    monkeypatch.setattr(agg, "ocr_pdf", _ocr)
    monkeypatch.setattr(agg, "call_llm", _llm_returning(json.dumps(_GOOD_CLAIMS)))
    user = CurrentUser(user_id=uid, email="t@example.com")

    started = await profile_routes.start_cv_upload(files=[_upload()], user=user)
    done = await _poll(started["task_id"], user)
    assert done["status"] == "done"
    assert _cv_data(uid)["skills"] == ["SQL"]


async def test_failed_task_reports_its_code(uid, monkeypatch):
    monkeypatch.setattr(agg, "extract_text", lambda content, name: "regulations")
    monkeypatch.setattr(agg, "call_llm", _llm_returning(json.dumps(_EMPTY_CLAIMS)))
    user = CurrentUser(user_id=uid, email="t@example.com")

    started = await profile_routes.start_cv_upload(files=[_upload()], user=user)
    failed = await _poll(started["task_id"], user)
    assert failed["status"] == "error"
    assert failed["status_code"] == 422
    assert failed["detail"]["code"] == "not_a_cv"


async def test_task_is_invisible_to_other_users(uid, monkeypatch):
    monkeypatch.setattr(agg, "extract_text", lambda content, name: "Analyst at Acme, SQL")
    monkeypatch.setattr(agg, "call_llm", _llm_returning(json.dumps(_GOOD_CLAIMS)))
    owner = CurrentUser(user_id=uid, email="t@example.com")
    started = await profile_routes.start_cv_upload(files=[_upload()], user=owner)

    stranger = CurrentUser(user_id=str(uuid.uuid4()), email="x@example.com")
    with pytest.raises(HTTPException) as exc:
        await profile_routes.get_cv_upload_status(started["task_id"], user=stranger)
    assert exc.value.status_code == 404
    await _poll(started["task_id"], owner)   # let the task finish before cleanup
