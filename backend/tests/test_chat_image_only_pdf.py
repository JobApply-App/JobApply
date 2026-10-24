"""
A CV whose PDF has no text layer still reaches Ariel and the profile.

Daniel's CV was exported from Canva as a single page image inside a PDF —
no fonts, no text. Uploaded in the Ariel chat, it was dropped from the
message (she was told to look at a file she never received) and the
background ingestion skipped it silently, so the CV never reached the
profile. The upload screens already OCR'd such files; the chat did not.
"""
import base64

from backend.api.routes import chat


def _pdf_item():
    return chat.AttachmentItem(
        base64=base64.b64encode(b"%PDF-1.4\n...image only...").decode(),
        filename="cv.pdf", mimeType="application/pdf",
    )


def test_image_only_pdf_is_passed_to_ariel_as_a_document(monkeypatch):
    monkeypatch.setattr(chat, "_extract_text_from_attachment", lambda item: None)
    content = chat._build_message_with_attachments("Please look at my CV", [_pdf_item()])
    assert isinstance(content, list)
    assert any(b.get("type") == "document" for b in content)
    assert content[-1]["type"] == "text" and "Please look at my CV" in content[-1]["text"]


def test_pdf_with_text_is_still_sent_as_text(monkeypatch):
    monkeypatch.setattr(chat, "_extract_text_from_attachment", lambda item: "Product Manager at Acme")
    content = chat._build_message_with_attachments("Please look at my CV", [_pdf_item()])
    assert isinstance(content, str) and "Product Manager at Acme" in content


def test_chat_ingestion_ocrs_a_pdf_with_no_text(monkeypatch):
    from backend.services import cv_aggregator_service as agg
    calls = {}

    async def _ocr(content, filename, user_id):
        calls["ocr"] = filename
        return "Daniel Shahmoon — Head of marketing, Strauss"

    async def _aggregate(texts, user_id):
        calls["aggregated"] = texts
        return {}   # stop before persisting
    monkeypatch.setattr(agg, "extract_text", lambda content, name: "")
    monkeypatch.setattr(agg, "ocr_pdf", _ocr)
    monkeypatch.setattr(agg, "aggregate_cv_claims", _aggregate)
    monkeypatch.setattr(agg, "claims_have_cv_content", lambda claims: False)

    chat._ingest_cv_from_chat("00000000-0000-0000-0000-000000000001", _pdf_item())
    assert calls["ocr"] == "cv.pdf"
    assert calls["aggregated"] == ["Daniel Shahmoon — Head of marketing, Strauss"]
