"""
Location and LinkedIn are recommended, not required. Tailoring used to block
on location like on name and phone, and never asked for LinkedIn. Each can now
be skipped once and is not asked again.
"""
from __future__ import annotations

from backend.agents import tailor


def _gaps(monkeypatch, personal):
    monkeypatch.setattr(tailor, "_resolve_profile", lambda uid: {"personal": personal})
    return tailor._core_profile_gaps("u1")


def test_missing_optional_fields_are_asked_and_marked_optional(monkeypatch):
    gaps = _gaps(monkeypatch, {"name": "A", "phone": "1"})
    assert [g["id"] for g in gaps] == ["core_location", "core_linkedin"]
    assert all(g["optional"] for g in gaps)


def test_skipped_fields_are_not_asked_again(monkeypatch):
    personal = {"name": "A", "phone": "1", "location_skipped": True, "linkedin_skipped": True}
    assert _gaps(monkeypatch, personal) == []


def test_linkedin_from_the_cv_is_not_asked(monkeypatch):
    personal = {"name": "A", "phone": "1", "location": "Haifa", "linkedin": "linkedin.com/in/a"}
    assert _gaps(monkeypatch, personal) == []


def test_name_and_phone_stay_required(monkeypatch):
    personal = {"location_skipped": True, "linkedin_skipped": True}
    assert {g["id"] for g in _gaps(monkeypatch, personal)} == {"core_name", "core_phone"}
