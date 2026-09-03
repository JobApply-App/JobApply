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
