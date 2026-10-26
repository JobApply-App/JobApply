"""
The exported CV is read back the way an ATS reads it — the PDF's text layer —
and contact details that don't come out as literal text are reported.

An ATS never sees the rendered page. A phone drawn as an icon glyph, or an
email split by the layout, looks fine on screen and is invisible to the
parser. ats_text_issues() catches that on every build_pdf() call.
"""
from __future__ import annotations

import fitz

from backend.services.pdf_builder import ats_text_issues

_CONTACT = {"name": "Dana Levi", "email": "dana.levi@example.com", "phone": "+972-54-123-4567"}


def _pdf(*pages: str) -> bytes:
    doc = fitz.open()
    for body in pages:
        doc.new_page().insert_text((72, 72), body)
    data = doc.tobytes()
    doc.close()
    return data


def test_clean_one_page_cv_has_no_issues():
    pdf = _pdf("Dana Levi\ndana.levi@example.com | 054 123 4567\nSenior Product Manager")
    assert ats_text_issues(pdf, _CONTACT) == []


def test_missing_contact_details_are_reported():
    pdf = _pdf("Dana Levi\nSenior Product Manager")
    assert ats_text_issues(pdf, _CONTACT) == ["email", "phone"]


def test_spill_onto_second_page_is_reported():
    pdf = _pdf("Dana Levi dana.levi@example.com 0541234567", "Education")
    assert ats_text_issues(pdf, _CONTACT) == ["pages=2"]


def test_image_only_pdf_has_no_text_layer():
    assert "no_text_layer" in ats_text_issues(_pdf(""), _CONTACT)


def test_absent_contact_fields_are_not_required():
    assert ats_text_issues(_pdf("Dana Levi"), {"name": "Dana Levi", "email": "", "phone": ""}) == []


def test_hebrew_name_in_visual_word_order_counts_as_present():
    pdf = _pdf("Levi Dana dana.levi@example.com 054-123-4567")
    assert ats_text_issues(pdf, _CONTACT) == []


def test_unreadable_bytes_never_raise():
    assert ats_text_issues(b"not a pdf", _CONTACT) == ["unreadable"]
