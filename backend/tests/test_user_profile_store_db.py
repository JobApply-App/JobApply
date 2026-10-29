"""
user_profile_store wrote per-user JSON files to the server's local disk, which
Render wipes on every deploy and restart: a phone edited in the profile, a
LinkedIn URL or supplemental answers vanished with the next release. The store
is now the profile document's metrics_doc in Postgres.
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text


@pytest.fixture()
def user(db_available):
    from backend.core.database import ENGINE
    uid = str(uuid.uuid4())
    with ENGINE.begin() as c:
        c.execute(text("INSERT INTO public.profiles (id, email) VALUES (CAST(:u AS uuid), :e)"),
                  {"u": uid, "e": f"store-{uid[:8]}@example.invalid"})
    yield uid
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": uid})


def test_saved_fields_and_answers_survive_without_any_local_file(user, tmp_path, monkeypatch):
    from backend.services import user_profile_store as store
    monkeypatch.setattr(store, "_LEGACY_USERS_DIR", tmp_path)   # an empty disk
    p = store.load(user)
    p["personal"]["phone"] = "050-1234567"
    store.save(user, p)
    store.merge_answers(user, {"team_size": "6"})
    assert not any(tmp_path.iterdir()), "nothing may be written to local disk"
    again = store.load(user)
    assert again["personal"]["phone"] == "050-1234567"
    assert store.get_cached_answer(user, "team_size") == "6"


def test_cv_claims_are_not_copied_into_the_store(user, tmp_path, monkeypatch):
    from backend.services import user_profile_store as store
    monkeypatch.setattr(store, "_LEGACY_USERS_DIR", tmp_path)
    p = store.load(user)
    p["cv_claims"] = {"skills": ["SQL"]}
    store.save(user, p)
    assert "cv_claims" not in store.load(user)


def test_a_file_left_on_disk_is_imported_once(user, tmp_path, monkeypatch):
    from backend.services import user_profile_store as store
    monkeypatch.setattr(store, "_LEGACY_USERS_DIR", tmp_path)
    f = tmp_path / user / "profile.json"
    f.parent.mkdir()
    f.write_text(json.dumps({"version": 1, "personal": {"linkedin_url": "https://linkedin.com/in/x"},
                             "metrics": {"q1": {"value": "a"}}}))
    doc = store.load(user)
    assert doc["personal"]["linkedin_url"] == "https://linkedin.com/in/x"
    assert doc["metrics"]["q1"]["value"] == "a"
    assert not f.exists() and f.with_suffix(".json.imported").exists()


def test_a_failed_read_raises_instead_of_returning_an_empty_document(monkeypatch):
    from backend.services import master_profile_service, user_profile_store as store
    from backend.repositories import profile_repository

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(profile_repository, "get_or_create", boom)
    with pytest.raises(RuntimeError):
        store.load(str(uuid.uuid4()))
    assert master_profile_service.load(str(uuid.uuid4()))["metrics"] == {}  # lenient default unchanged
