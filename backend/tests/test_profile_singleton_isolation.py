"""
Regression guard: the legacy USER_PROFILE singleton must never reach a caller.

Why this file exists
--------------------
Four live code paths used to serve `backend.services.user_profile.USER_PROFILE`
— one real person's full career history, education and phone number — to
whichever account happened to be calling:

  * chat.py::_build_system_prompt      injected it into every Ariel conversation,
                                       labelled "verified — treat as ground truth"
  * master_profile_service._empty_profile()  seeded every NEW account's personal
                                       block from it
  * profile_interviewer._build_profile_context  read experience/education from it
  * user_profile.resolve_profile()     returned it on any DB error

The full suite passed with all four in place, which is the point of this file:
these are data-isolation properties, not behaviours any feature test happens to
observe. Each test below fails against the pre-fix code.

Deliberately no DB: every assertion here is about which SOURCE a function reads,
so the tests stay runnable anywhere (CI without Postgres included).
"""
from __future__ import annotations

import inspect

import pytest


def _singleton() -> dict:
    from backend.services.user_profile import USER_PROFILE
    return USER_PROFILE


def _singleton_contact_markers() -> list[str]:
    """
    Contact values from the singleton — present only where the gitignored
    backend/personal_overrides.json exists (a developer machine, or a deploy
    that ships that file). In a clean checkout this block is blank, so tests
    using these markers must skip rather than pass vacuously.
    """
    p = _singleton().get("personal", {}) or {}
    vals = [str(p.get(k) or "").strip() for k in ("phone", "location", "email")]
    return [v for v in vals if len(v) > 3]


def _singleton_career_markers() -> list[str]:
    """
    Employer names from the singleton. Unlike the contact block these are
    literals in tracked source, so they are present in every environment —
    which makes them the reliable leak detector.
    """
    return [
        str(e.get("company") or "").strip()
        for e in (_singleton().get("experience") or [])
        if len(str(e.get("company") or "").strip()) > 3
    ]


class TestResolveProfileFailsClosed:
    def test_returns_empty_dict_when_lookup_raises(self, monkeypatch):
        """A DB error must yield {}, never the singleton."""
        import backend.services.user_profile as up

        def _boom(_user_id):
            raise RuntimeError("simulated DB outage")

        monkeypatch.setattr(up, "get_profile", _boom)
        result = up.resolve_profile("a2c1f0de-0000-4000-8000-000000000001")

        assert result == {}, "resolve_profile must fail closed, not fall back to a global profile"
        assert result is not up.USER_PROFILE

    def test_failure_result_carries_no_singleton_career_history(self, monkeypatch):
        import backend.services.user_profile as up

        monkeypatch.setattr(up, "get_profile", lambda _u: (_ for _ in ()).throw(RuntimeError("x")))
        blob = repr(up.resolve_profile("a2c1f0de-0000-4000-8000-000000000002"))

        markers = _singleton_career_markers()
        assert markers, "singleton has no employers to test against — check the fixture"
        for marker in markers:
            assert marker not in blob, f"singleton employer {marker!r} leaked through resolve_profile"


class TestNewProfileScaffoldIsBlank:
    def test_empty_profile_personal_block_is_empty(self):
        """A brand-new account must not be born holding someone else's details."""
        from backend.services.master_profile_service import _empty_profile

        personal = _empty_profile().get("personal", {})
        assert personal, "scaffold should still declare the personal keys"
        for field, value in personal.items():
            assert value == "", f"new-profile scaffold pre-filled {field}={value!r}"

    def test_empty_profile_carries_no_singleton_contact_details(self):
        """
        Only meaningful where personal_overrides.json is present — see
        _singleton_contact_markers. Skipped rather than passed vacuously in a
        clean checkout, so a green run here always means something was checked.
        """
        from backend.services.master_profile_service import _empty_profile

        markers = _singleton_contact_markers()
        if not markers:
            pytest.skip("no local personal_overrides.json — contact block is blank, nothing to leak")

        blob = repr(_empty_profile())
        for marker in markers:
            assert marker not in blob, f"singleton contact value {marker!r} leaked into a new profile"


class TestProfileReadersAreUserScoped:
    """
    Signature-level guard. A profile-bearing prompt builder that can be called
    without a user_id is one refactor away from serving the wrong person's data,
    so require the parameter to exist and be mandatory.
    """

    @pytest.mark.parametrize(
        "module_path, func_name",
        [
            ("backend.api.routes.chat", "_build_system_prompt"),
            ("backend.agents.profile_interviewer", "_build_profile_context"),
        ],
    )
    def test_takes_a_required_user_id(self, module_path, func_name):
        import importlib

        fn = getattr(importlib.import_module(module_path), func_name)
        params = inspect.signature(fn).parameters

        assert "user_id" in params, f"{func_name} must be scoped to a user_id"
        assert params["user_id"].default is inspect.Parameter.empty, (
            f"{func_name}'s user_id must be required — an optional one silently "
            "reintroduces a global default"
        )


class TestSingletonIsNotImportedByCallers:
    """
    The singleton stays importable (user_profile.py owns it, and the legacy
    Streamlit app still reads it), but no live backend module should pull it in:
    an unused import is exactly how the next accidental reuse gets written.
    """

    def test_no_live_module_imports_the_singleton(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1]
        allowed = {root / "services" / "user_profile.py"}
        pattern = re.compile(r"^\s*from\s+backend\.services\.user_profile\s+import\s+(.+)$", re.M)

        offenders = []
        for path in root.rglob("*.py"):
            if path in allowed or "tests" in path.parts or "logic" in path.parts:
                continue
            for imported in pattern.findall(path.read_text(encoding="utf-8")):
                if "USER_PROFILE" in imported:
                    offenders.append(str(path.relative_to(root)))

        assert not offenders, (
            "these modules import the legacy USER_PROFILE singleton; read the "
            f"caller's own profile instead: {offenders}"
        )


class TestPromptsCarryNoPersonalFacts:
    """
    The system prompts are shared by every user, so a name, employer or metric
    written into one is that person's data injected into everyone else's output.

    This is a different failure mode from the singleton leaks above and was a
    real one: tailor.py's CV doctrine used to be a per-employer strategy table
    ("GO-OUT ... Always gets primary slot. Lead with scope: 800+ clients, 7
    direct reports"), and outreach_service.py hardcoded one candidate's career
    domain into messages sent to real recruiters. Both now derive from the
    profile the prompt already receives.

    A find/replace here is worse than nothing, so the guard is on the facts,
    not the labels: renaming "Ron's" to "the candidate's" while leaving
    "800+ clients" in place would read generic and behave wrong.
    """

    # Employers, metrics and tooling that belonged to one real profile.
    _PERSONAL_FACTS = (
        "GO-OUT", "GO_OUT", "Pitango", "Reuveni", "Aldo (Gelato",
        "Insurance Agency", "Seats.io", "TAMA AR",
        "800+ clients", "40+ B2B", "7 direct reports", "120 accounts",
        "Israel + Greece", "3 concurrent jobs",
    )

    @pytest.mark.parametrize(
        "module_path, attr",
        [
            ("backend.agents.tailor", "_SYSTEM_PROMPT"),
            ("backend.services.outreach_service", "_SYSTEM"),
            ("backend.services.outreach_service", "_CONSULTATION_TMPL"),
            ("backend.services.outreach_service", "_ESCALATION_TMPL"),
            ("backend.services.outreach_service", "_HEADHUNTER_TMPL"),
            ("backend.agents.copilot", "_SYSTEM_PROMPT"),
        ],
    )
    def test_prompt_names_no_specific_person_or_employer(self, module_path, attr):
        import importlib

        module = importlib.import_module(module_path)
        prompt = getattr(module, attr, None)
        if prompt is None:
            pytest.skip(f"{module_path}.{attr} no longer exists")

        found = [fact for fact in self._PERSONAL_FACTS if fact.lower() in prompt.lower()]
        assert not found, (
            f"{module_path}.{attr} contains one profile's specific facts {found}. "
            "Prompts are shared by every user — take these from CANDIDATE_PROFILE "
            "at build time instead."
        )

    @pytest.mark.parametrize(
        "module_path, attr",
        [
            ("backend.agents.tailor", "_SYSTEM_PROMPT"),
            ("backend.services.outreach_service", "_SYSTEM"),
            ("backend.services.outreach_service", "_CONSULTATION_TMPL"),
            ("backend.services.outreach_service", "_HEADHUNTER_TMPL"),
        ],
    )
    def test_prompt_refers_to_the_candidate_generically(self, module_path, attr):
        """Catches the possessive form a rename usually misses first."""
        import importlib
        import re

        prompt = getattr(importlib.import_module(module_path), attr, None)
        if prompt is None:
            pytest.skip(f"{module_path}.{attr} no longer exists")

        # A bare given name followed by "'s" — the shape "Ron's background" had.
        offenders = re.findall(r"\b[A-Z][a-z]{2,}'s\b", prompt)
        allowed = {"Today's", "Candidate's", "Company's", "Manager's", "Dean's", "Hiring's"}
        offenders = [o for o in offenders if o not in allowed]
        assert not offenders, (
            f"{module_path}.{attr} refers to a specific person: {sorted(set(offenders))}"
        )
