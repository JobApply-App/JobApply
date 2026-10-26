"""
Uploaded PDFs reach the verifier as text — or, when scanned, as the PDF itself.

_extract_pdf_text() used to import pypdf, which is not installed; a broad
except turned the ImportError into "", so every PDF a user uploaded to verify
a claim came back "unreadable". Scanned diplomas (no text layer) were also
rejected outright although Claude reads PDFs natively.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import fitz
import pytest

from backend.services import document_verifier as dv

_CLAIM = "BA in Business Administration from Reichman University"


def _pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    else:
        page.draw_rect(fitz.Rect(72, 72, 300, 200), fill=(0, 0, 0))  # a "scan": ink, no text
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def fake_call_llm(**kwargs):
        calls.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(text=json.dumps({"status": "verified", "match_notes": "ok", "extracted_facts": {}}))

    monkeypatch.setattr(dv, "call_llm", fake_call_llm)
    return calls


def test_text_pdf_is_extracted():
    text = "Reichman University hereby certifies that the bearer completed a BA in Business Administration."
    assert "Reichman University" in dv._extract_pdf_text(_pdf(text))


async def test_text_pdf_is_verified_from_its_text(sent):
    text = "Reichman University hereby certifies that the bearer completed a BA in Business Administration."
    result = await dv.verify_document(file_content=_pdf(text), filename="diploma.pdf", claim=_CLAIM)
    assert result["status"] == "verified"
    assert "Reichman University hereby certifies" in sent[0][0]["text"]


async def test_scanned_pdf_is_sent_as_a_document(sent):
    result = await dv.verify_document(file_content=_pdf(""), filename="scan.pdf", claim=_CLAIM)
    assert result["status"] == "verified"
    blocks = sent[0]
    assert blocks[1]["type"] == "document"
    assert blocks[1]["source"]["media_type"] == "application/pdf"
