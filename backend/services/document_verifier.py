"""
Document Verification Service.

Accepts an uploaded file (PDF or image), extracts its text content, then uses
Claude to cross-reference the text against a stated claim from the candidate's
draft profile.

Verification outcomes
----------------------
  VERIFIED   — the document clearly supports the claim (confidence → 100%)
  PARTIAL    — the document is relevant but doesn't fully confirm all details (75%)
  FAILED     — the document contradicts or is unrelated to the claim (score unchanged)
  UNREADABLE — text extraction failed or the document is too blurry/corrupt

Supported file types
---------------------
  PDF    — text extracted with pymupdf; a scanned PDF (no text layer) is sent
           to Claude as a document block, which reads it page by page
  Images — PNG, JPG, JPEG, WEBP — passed directly to Claude vision API
"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from backend.services.llm_client import call_llm

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

logger = logging.getLogger(__name__)

_MODEL      = "claude-haiku-4-5"  # vision-capable; fast for document reading
_MAX_TOKENS = 800

VerificationStatus = Literal["verified", "partial", "failed", "unreadable"]

CONF_BOOST = {
    "verified": 100,
    "partial":  75,
    "failed":   None,   # do not change
    "unreadable": None,
}

_VERIFY_SYSTEM = """\
You are a document verification specialist. You receive the text content of an \
uploaded document and a claim made by a job candidate. Your job is to determine \
whether the document supports, partially supports, or contradicts the claim.

OUTPUT ONLY a raw JSON object:
{
  "status":      "verified | partial | failed | unreadable",
  "confidence":  100 | 75 | 30 | 0,
  "match_notes": "1-2 sentences explaining what the document confirms or is missing",
  "extracted_facts": {
    "institution": "exact name found in document or null",
    "degree":      "exact degree found in document or null",
    "dates":       "date range found in document or null",
    "gpa":         "GPA or honor found in document or null",
    "name":        "candidate name found in document or null"
  }
}

RULES:
• "verified"   = document clearly and explicitly confirms the claim
• "partial"    = document is relevant but is missing one or more key details
• "failed"     = document is unrelated, contradicts the claim, or appears forged
• "unreadable" = you cannot read the document content
• Be strict: if the document doesn't name the institution explicitly, say partial.
"""


def _extract_pdf_text(content: bytes) -> str:
    """Extract plain text from a PDF using pymupdf."""
    try:
        import fitz
        with fitz.open(stream=content, filetype="pdf") as doc:
            pages = [page.get_text() for page in doc.pages(0, min(10, doc.page_count))]  # cap at 10 pages
        return "\n".join(pages).strip()
    except Exception as exc:
        logger.warning("[DocumentVerifier] PDF extraction failed: %s", exc)
        return ""


def _image_to_base64(content: bytes, mime_type: str) -> str:
    return base64.standard_b64encode(content).decode("utf-8")


async def verify_document(
    *,
    file_content:  bytes,
    filename:      str,
    claim:         str,
    document_type: str = "document",
) -> dict:
    """
    Verify a document against a stated claim.

    Parameters
    ----------
    file_content  : raw bytes of the uploaded file
    filename      : original filename (used to detect type)
    claim         : the candidate's stated claim to verify against
                    (e.g. "BA in Business Administration from Reichman University")
    document_type : human-readable label for logs (e.g. "transcript", "diploma")

    Returns
    -------
    dict with keys: status, confidence, match_notes, extracted_facts
    """
    ext    = Path(filename).suffix.lower()

    user_content: list = []

    if ext == ".pdf":
        # Extract text, send as text content
        pdf_text = _extract_pdf_text(file_content)
        if not pdf_text or len(pdf_text) < 50:
            # A scanned diploma or certificate has no text layer. Claude reads
            # PDFs natively, so hand it the file instead of giving up.
            logger.info("[DocumentVerifier] no text layer, sending PDF as a document: %s", filename)
            user_content = [
                {
                    "type": "text",
                    "text": (
                        f"DOCUMENT TYPE: {document_type}\n"
                        f"CLAIM TO VERIFY: {claim}\n\n"
                        f"Read the attached document and verify the claim."
                    ),
                },
                {
                    "type":   "document",
                    "source": {
                        "type":       "base64",
                        "media_type": "application/pdf",
                        "data":       base64.standard_b64encode(file_content).decode(),
                    },
                },
            ]
        else:
            # Truncate to first 3000 chars to stay within token budget
            user_content = [
                {
                    "type": "text",
                    "text": (
                        f"DOCUMENT TYPE: {document_type}\n"
                        f"CLAIM TO VERIFY: {claim}\n\n"
                        f"DOCUMENT TEXT:\n{pdf_text[:3000]}"
                    ),
                }
            ]

    elif ext in {".png", ".jpg", ".jpeg", ".webp"}:
        # Use vision API
        mime_map = {".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")
        b64 = _image_to_base64(file_content, mime_type)
        user_content = [
            {
                "type": "text",
                "text": (
                    f"DOCUMENT TYPE: {document_type}\n"
                    f"CLAIM TO VERIFY: {claim}\n\n"
                    f"Read the document image below and verify the claim."
                ),
            },
            {
                "type":   "image",
                "source": {
                    "type":       "base64",
                    "media_type": mime_type,
                    "data":       b64,
                },
            },
        ]
    else:
        return {
            "status":          "unreadable",
            "confidence":      None,
            "match_notes":     f"Unsupported file type: {ext}",
            "extracted_facts": {},
        }

    try:
        result_llm = await call_llm(
            system     = _VERIFY_SYSTEM,
            messages   = [{"role": "user", "content": user_content}],
            model      = _MODEL,
            max_tokens = _MAX_TOKENS,
            purpose    = "document_verify",
        )
        raw    = result_llm.text.strip()
        import json, re
        raw    = re.sub(r"```(?:json)?", "", raw).strip()
        result = json.loads(raw)
    except Exception as exc:
        logger.error("[DocumentVerifier] Verification call failed: %s", exc)
        result = {
            "status":          "unreadable",
            "confidence":      None,
            "match_notes":     f"Verification error: {exc}",
            "extracted_facts": {},
        }

    # Override confidence with our canonical values
    status      = result.get("status", "unreadable")
    new_conf    = CONF_BOOST.get(status)
    result["confidence"] = new_conf

    logger.info(
        "[DocumentVerifier] %s — status=%s  confidence=%s  file=%s",
        document_type, status, new_conf, filename,
    )
    return result
