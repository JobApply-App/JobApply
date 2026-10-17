"""
get_locales() must keep three outcomes apart.

It used to return DEFAULT_LOCALE for all of them: no stored preference, a
value outside SUPPORTED_LOCALES, and a database that could not be read. The
frontend adopts whatever it receives and writes it to the locale cookie, so
the third case meant a failed query silently replaced a language the visitor
had actively chosen — a read rewriting user state.

These tests pin the distinction rather than the defaulting, so a future
change that reintroduces a friendly fallback fails here instead of in a
user's browser.
"""
from __future__ import annotations

import uuid

import pytest

from backend.repositories import profile_repository as pr


def _fake_engine(row):
    """A connection whose query succeeds and returns `row` (None = no row).

    Stubbed rather than hitting a real database on purpose: this module
    asserts how a result is interpreted, which should not depend on whether
    the machine running it happens to have a populated Postgres — the exact
    coupling that let the original bug hide.
    """
    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **kw):
            class _R:
                def fetchone(_self): return row
            return _R()
    return lambda: _Conn()


def test_unset_preference_is_none_not_english(monkeypatch):
    """
    None means "this account never chose", which the client reads as "leave
    the visitor's own selection alone". Answering 'en' here is what let a
    Hebrew reader get flipped to English merely by signing in.
    """
    monkeypatch.setattr(pr.ENGINE, "connect", _fake_engine(None))
    got = pr.get_locales(str(uuid.uuid4()))
    assert got == {"ui_locale": None, "cv_locale": None}


def test_stored_preference_is_returned(monkeypatch):
    monkeypatch.setattr(pr.ENGINE, "connect", _fake_engine(("he", "en")))
    got = pr.get_locales(str(uuid.uuid4()))
    assert got == {"ui_locale": "he", "cv_locale": "en"}


def test_malformed_user_id_is_none_not_english():
    got = pr.get_locales("not-a-uuid")
    assert got == {"ui_locale": None, "cv_locale": None}


def test_unreadable_database_raises_instead_of_defaulting(monkeypatch):
    """
    The case that caused the bug. A caller must be able to tell an
    infrastructure failure from a preference, so this raises rather than
    returning a plausible-looking language.
    """
    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(pr.ENGINE, "connect", _boom)

    with pytest.raises(pr.LocalesUnavailable):
        pr.get_locales(str(uuid.uuid4()))


def test_value_outside_supported_locales_is_not_served(monkeypatch):
    """
    A stored value that is not a language we support is not a preference we
    can honour — but it is also not a reason to invent one, so it reads as
    unset.
    """
    monkeypatch.setattr(pr.ENGINE, "connect", _fake_engine(("klingon", "he")))
    got = pr.get_locales(str(uuid.uuid4()))
    assert got["ui_locale"] is None      # unsupported → unknown, not 'en'
    assert got["cv_locale"] == "he"      # the valid half still comes through


# ── Against the real schema (migration 7d3e1a9b4c62) ─────────────────────────
# The tests above stub the DB. These pin what the column itself does, which is
# where the bug actually lived: ui_locale was NOT NULL DEFAULT 'en', so every
# account read back as "chose English" and the UI flipped Hebrew visitors back
# to English the moment they signed in.

import uuid as _uuid

import pytest as _pytest


@_pytest.fixture()
def fresh_uid(db_available):
    from sqlalchemy import text
    from backend.core.database import ENGINE
    u = str(_uuid.uuid4())
    with ENGINE.begin() as c:   # user_preferences has an FK to profiles
        c.execute(text("INSERT INTO public.profiles (id, onboarding_status) VALUES (CAST(:u AS uuid), 'incomplete')"), {"u": u})
    yield u
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.user_preferences WHERE user_id = CAST(:u AS uuid)"), {"u": u})
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": u})


def test_new_account_has_not_chosen_a_ui_language(fresh_uid):
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository

    # The ordinary write path every new account goes through creates the
    # user_preferences row without mentioning a locale.
    with Session(ENGINE) as s:
        row, _ = profile_repository.get_or_create(s, fresh_uid, now=datetime.now(timezone.utc).isoformat())
        profile_repository.save(s, row)
        s.commit()
    assert profile_repository.get_locales(fresh_uid)["ui_locale"] is None


def test_choosing_only_the_cv_language_does_not_choose_the_ui_language(fresh_uid):
    from backend.repositories import profile_repository
    profile_repository.set_locales(fresh_uid, cv_locale="he")
    got = profile_repository.get_locales(fresh_uid)
    assert got["ui_locale"] is None and got["cv_locale"] == "he"


def test_an_explicit_choice_is_stored(fresh_uid):
    from backend.repositories import profile_repository
    profile_repository.set_locales(fresh_uid, ui_locale="he")
    assert profile_repository.get_locales(fresh_uid)["ui_locale"] == "he"
