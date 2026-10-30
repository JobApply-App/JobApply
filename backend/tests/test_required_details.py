"""
Target roles with a level in each, and the Hebrew wording, are asked once:
at onboarding, or at the next login for anyone who skipped them. The Hebrew
wording used to be a Masculine/Feminine toggle inside the CV screen.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend.api.routes.profile as profile
import backend.api.routes.resumes as resumes


@pytest.fixture()
def store(monkeypatch):
    data = {"answers": {}, "profile": {}}
    repo = profile.profile_repository
    monkeypatch.setattr(repo, "get_answer", lambda uid, key: data["answers"].get(key))
    monkeypatch.setattr(repo, "set_answer", lambda uid, key, v: data["answers"].__setitem__(key, v))
    monkeypatch.setattr(repo, "get_profile_json", lambda uid, engine=None: data["profile"])
    return data


USER = SimpleNamespace(user_id="u1")


async def test_a_new_user_is_missing_both(store):
    assert (await profile.get_required_details(user=USER))["missing"] == ["roles", "hebrew_form"]


async def test_a_role_without_a_level_still_counts_as_missing(store):
    store["profile"]["role_preferences"] = {"roles": [{"role": "Product Manager", "seniority": ""}]}
    store["answers"]["cv_hebrew_gender"] = "f"
    assert (await profile.get_required_details(user=USER))["missing"] == ["roles"]


async def test_nothing_is_missing_once_answered(store):
    store["profile"]["role_preferences"] = {"roles": [{"role": "Product Manager", "seniority": "senior"}]}
    await profile.set_hebrew_form(profile.HebrewFormPayload(value="n"), user=USER)
    assert (await profile.get_required_details(user=USER))["missing"] == []


async def test_only_known_forms_are_saved(store):
    with pytest.raises(HTTPException):
        await profile.set_hebrew_form(profile.HebrewFormPayload(value="x"), user=USER)
    assert "cv_hebrew_gender" not in store["answers"]


@pytest.mark.parametrize("stored,expected", [("m", "m"), ("f", "f"), ("n", None), (None, None)])
def test_the_cv_uses_the_saved_form(store, stored, expected):
    store["answers"]["cv_hebrew_gender"] = stored
    assert resumes._resolve_cv_gender("u1", None) == expected
