"""
Every new CV opened in Modern, with no way to choose: a user who preferred
another design re-picked it each time. The user can now set a default.
"""
from types import SimpleNamespace

import pytest

import backend.api.routes.resumes as resumes
from backend.core.errors import AppError


@pytest.fixture()
def answers(monkeypatch):
    store = {}
    monkeypatch.setattr(resumes.profile_repository, "get_answer", lambda uid, key: store.get(key))
    monkeypatch.setattr(resumes.profile_repository, "set_answer", lambda uid, key, v: store.__setitem__(key, v))
    return store


USER = SimpleNamespace(user_id="u1")


async def test_new_cvs_open_in_the_users_default(answers):
    assert resumes._default_template("u1") == "t2_modern"
    await resumes.set_default_template(resumes.DefaultTemplateRequest(template_id="t5_techmodern"), user=USER)
    assert resumes._default_template("u1") == "t5_techmodern"
    assert (await resumes.list_templates(user=USER))["default_template"] == "t5_techmodern"


async def test_an_unknown_design_is_refused(answers):
    with pytest.raises(AppError):
        await resumes.set_default_template(resumes.DefaultTemplateRequest(template_id="nope"), user=USER)


def test_the_design_on_screen_wins_over_the_default(answers):
    answers["cv_default_template"] = "t1_classic"
    assert resumes._cv_template("u1", SimpleNamespace(template_id="t3_executive")) == "t3_executive"
    assert resumes._cv_template("u1", SimpleNamespace()) == "t1_classic"
