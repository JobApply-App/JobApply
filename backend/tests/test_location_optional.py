"""
Location is recommended, not required. Tailoring used to block on it like on
name and phone; the user can now skip it once and is not asked again.
"""
from __future__ import annotations

from backend.agents import tailor


def _gaps(monkeypatch, personal):
    monkeypatch.setattr(tailor, "_resolve_profile", lambda uid: {"personal": personal})
    return [g["id"] for g in tailor._core_profile_gaps("u1")]


def test_missing_location_is_asked_and_marked_optional(monkeypatch):
    monkeypatch.setattr(tailor, "_resolve_profile",
                        lambda uid: {"personal": {"name": "A", "phone": "1"}})
    gaps = tailor._core_profile_gaps("u1")
    assert [g["id"] for g in gaps] == ["core_location"]
    assert gaps[0]["optional"] is True


def test_skipped_location_is_not_asked_again(monkeypatch):
    assert _gaps(monkeypatch, {"name": "A", "phone": "1", "location_skipped": True}) == []


def test_name_and_phone_stay_required(monkeypatch):
    assert set(_gaps(monkeypatch, {"location_skipped": True})) == {"core_name", "core_phone"}
