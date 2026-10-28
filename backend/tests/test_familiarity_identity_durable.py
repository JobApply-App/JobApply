"""
Regression: a user's score fell 40.2 -> 38.2 with nothing changed on her side.

The familiarity score's identity anchors (name, phone, target roles) were read
only from user_profile_store — a JSON file on the server's local disk. Render
discards local disk when the container restarts; the file was recreated empty
and the "roles known" anchor (2.0 points) disappeared, although the roles were
saved in Postgres. load_identity_profile() reads Postgres first.
"""
from __future__ import annotations

import pytest

from backend.services import profile_update_service as pus


@pytest.fixture()
def wiped_disk(monkeypatch):
    """The local file store after a restart: an empty scaffold."""
    monkeypatch.setattr(
        "backend.services.user_profile_store.load",
        lambda uid: {"personal": {"full_name": "", "phone": ""},
                     "role_preferences": {"target_titles": []}},
    )
    monkeypatch.setattr(
        "backend.services.user_profile._auth_metadata_personal", lambda uid: {},
    )


def _postgres(monkeypatch, doc):
    monkeypatch.setattr(
        "backend.repositories.profile_repository.get_profile_json", lambda uid: doc,
    )


def test_roles_in_postgres_survive_a_wiped_disk(monkeypatch, wiped_disk):
    _postgres(monkeypatch, {
        "personal": {"name": "Sapir"},
        "metrics_doc": {"personal": {"phone": "050-0000000"}},
        "role_preferences": {"target_titles": ["Software Engineer"]},
    })
    anchors = pus.identity_anchors(pus.load_identity_profile("u1"))
    assert anchors == {"name": True, "phone": True, "roles": True}


def test_roles_told_to_ariel_count(monkeypatch, wiped_disk):
    _postgres(monkeypatch, {"career_goals": {"target_roles": ["Backend Developer"]}})
    assert pus.identity_anchors(pus.load_identity_profile("u1"))["roles"] is True


def test_score_identity_does_not_drop_after_restart(monkeypatch, wiped_disk):
    _postgres(monkeypatch, {"role_preferences": {"target_titles": ["Software Engineer"]}})
    svc = pus.ProfileUpdateService(engine=None)
    rows = [("skill", "unverified", None)] * 10
    br = svc._compute_familiarity_from_rows(rows, "u1")
    assert br["identity"]["roles"] is True
    with_roles = br["context"]

    _postgres(monkeypatch, {})
    without = svc._compute_familiarity_from_rows(rows, "u1")["context"]
    assert with_roles - without == pytest.approx(pus.ProfileUpdateService.CONTEXT_IDENTITY_MAX / 3, abs=0.1)
