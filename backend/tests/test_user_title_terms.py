"""
Each user's feed is filtered by THEIR roles, not one global list.

Until this existed, every automated source admitted a job only if its title
matched config.TARGET_SEARCH_QUERIES — the founder's own Product/CS/Ops roles.
The first real testers were a government-affairs lead, an FP&A analyst and a
digital marketing manager: of 8,560 catalog jobs only ~7% could reach any of
them, and all of those were Product/CS jobs none of them wanted. Meanwhile
no user had saved a target role, because onboarding kept "Continue" disabled
until every role had a seniority level, so everyone pressed Skip.

These tests pin: where a user's titles come from, how they are expanded and
cached, that the matcher is per-user (and falls back to the global list only
for a profile that names nothing), and that the all_jobs bridge actually
uses it.
"""
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.scrapers.relevancy import build_title_matcher, is_title_relevant
from backend.services import user_title_terms as utt


# ── Where a user's titles come from ──────────────────────────────────────────

def test_picked_roles_win_over_cv_titles():
    profile = {
        "role_preferences": {"target_titles": ["Digital Marketing Manager"]},
        "cv_data": {"experiences": [{"title": "Barista"}]},
    }
    assert utt.source_titles(profile) == ["Digital Marketing Manager"]


def test_skipped_onboarding_falls_back_to_recent_cv_titles():
    profile = {"cv_data": {"experiences": [
        {"title": "FP&A Analyst"}, {"title": "Customer Relations"},
        {"title": "fp&a analyst"}, {"title": "Office Manager"}, {"title": "Commander"},
    ]}}
    assert utt.source_titles(profile) == ["FP&A Analyst", "Customer Relations", "Office Manager"]


def test_profile_with_no_titles_has_no_source():
    assert utt.source_titles({}) == []


def test_deterministic_expansion_strips_seniority():
    terms = utt.deterministic_terms(["Senior FP&A Analyst", "Head of Policy"])
    assert "FP&A Analyst" in terms and "Policy" in terms


# ── The matcher ──────────────────────────────────────────────────────────────

def test_matcher_is_per_user():
    marketing = build_title_matcher(["Digital Marketing", "מנהל שיווק"])
    assert marketing("Digital Marketing Manager - Tel Aviv")
    assert marketing("מנהל/ת שיווק דיגיטלי")       # Hebrew slash gender form
    assert not marketing("Senior Product Manager")  # the founder's role, not theirs


def test_short_terms_need_word_boundaries():
    m = build_title_matcher(["PM", "FP&A"])
    assert m("PM Lead") and m("Senior FP&A Analyst")
    assert not m("npm developer")


def test_no_terms_means_the_global_gate():
    assert build_title_matcher(None) is is_title_relevant
    assert build_title_matcher([]) is is_title_relevant


# ── Expansion: LLM, with a loud deterministic fallback ───────────────────────

async def test_expansion_uses_llm_output(monkeypatch):
    async def _fake(**_k):
        return SimpleNamespace(text='["Financial Analyst", "אנליסט פיננסי"]')
    monkeypatch.setattr("backend.services.llm_client.call_llm", _fake)
    terms = await utt.expand_titles(["FP&A Analyst"], user_id="u")
    assert terms[0] == "FP&A Analyst"            # the user's own title is always kept
    assert "אנליסט פיננסי" in terms


async def test_expansion_survives_llm_failure(monkeypatch):
    async def _boom(**_k):
        raise RuntimeError("provider down")
    monkeypatch.setattr("backend.services.llm_client.call_llm", _boom)
    terms = await utt.expand_titles(["Senior FP&A Analyst"], user_id="u")
    assert "FP&A Analyst" in terms


# ── Caching (Postgres-backed) ────────────────────────────────────────────────

@pytest.fixture()
def uid(db_available):
    from backend.core.database import ENGINE
    u = str(uuid.uuid4())
    yield u
    with ENGINE.begin() as c:
        for table in ("cv_documents", "profile_answers", "user_preferences"):
            c.execute(text(f"DELETE FROM public.{table} WHERE user_id = CAST(:u AS uuid)"), {"u": u})
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": u})


def _set_roles(uid: str, roles: list[str]) -> None:
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository
    with Session(ENGINE) as s:
        row, _ = profile_repository.get_or_create(s, uid, now=datetime.now(timezone.utc).isoformat())
        mp = dict(row.master_profile or {})
        mp["role_preferences"] = {"target_titles": roles, "roles": [{"role": r, "seniority": ""} for r in roles]}
        row.master_profile = mp
        profile_repository.save(s, row)
        s.commit()


async def test_terms_are_cached_until_the_roles_change(uid, monkeypatch):
    calls = []

    async def _fake(**kw):
        calls.append(kw["messages"][0]["content"])
        return SimpleNamespace(text='["Marketing Manager"]')
    monkeypatch.setattr("backend.services.llm_client.call_llm", _fake)

    _set_roles(uid, ["Digital Marketing Manager"])
    first = await utt.refresh_user_terms(uid)
    second = await utt.refresh_user_terms(uid)
    assert first == second and "Marketing Manager" in first
    assert len(calls) == 1                      # second call served from cache
    assert utt.cached_user_terms(uid) == first

    _set_roles(uid, ["Campaign Manager"])
    await utt.refresh_user_terms(uid)
    assert len(calls) == 2                      # roles changed -> regenerated


async def test_user_with_no_titles_gets_none(uid):
    _set_roles(uid, [])
    assert await utt.refresh_user_terms(uid) is None


# ── The all_jobs bridge uses the user's matcher ──────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_catalog_index():
    from backend.services import all_jobs_match_service as svc
    svc._INDEX_CACHE.update(at=0.0, rows=None)
    yield
    svc._INDEX_CACHE.update(at=0.0, rows=None)


@pytest.fixture()
def catalog(db_available):
    """Two all_jobs rows: one marketing, one product."""
    from backend.core.postgres import PG_ENGINE
    now = datetime.now(timezone.utc)
    tag = uuid.uuid4().hex[:8]
    rows = {
        "marketing": f"https://example.com/jobs/marketing-{tag}",
        "product":   f"https://example.com/jobs/product-{tag}",
    }
    titles = {"marketing": "Digital Marketing Manager", "product": "Senior Product Manager"}
    with PG_ENGINE.begin() as c:
        for key, url in rows.items():
            c.execute(text("""
                INSERT INTO public.all_jobs
                    (id, source, canonical_job_key, first_seen_at, last_seen_at, insertion_time,
                     updated_at, created_at, job_title, company_name, job_url, normalized_job_url)
                VALUES (CAST(:id AS uuid), 'linkedin', :key, :now, :now, :now, :now, :now,
                        :title, 'Acme', :url, :url)
            """), {"id": str(uuid.uuid4()), "key": url, "now": now, "title": titles[key], "url": url})
    yield rows
    with PG_ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.all_jobs WHERE job_url = ANY(:u)"), {"u": list(rows.values())})


def _capture_saves(monkeypatch):
    captured = {}

    class _FakeScraperManager:
        @staticmethod
        def _save_new(jobs, limit=None, user_id=None, matcher=None):
            captured["urls"] = [j.apply_url for j in jobs]
            return len(jobs)

    monkeypatch.setattr("backend.scrapers.scraper_manager.ScraperManager", _FakeScraperManager)
    return captured


def test_bridge_admits_the_users_roles_not_the_global_list(catalog, monkeypatch):
    from backend.services import all_jobs_match_service as svc
    monkeypatch.setattr(svc, "_existing_job_ids", lambda user_id: set())
    captured = _capture_saves(monkeypatch)

    svc.run_all_jobs_matching_cycle(str(uuid.uuid4()), limit=500, terms=["Digital Marketing"])
    assert catalog["marketing"] in captured["urls"]
    assert catalog["product"] not in captured["urls"]


def test_bridge_without_terms_adds_nothing(catalog, monkeypatch):
    # The global list is the founder's own roles; a user whose roles are not
    # known yet must not be fed those (a software engineer got Product jobs).
    from backend.services import all_jobs_match_service as svc
    monkeypatch.setattr(svc, "_existing_job_ids", lambda user_id: set())
    captured = _capture_saves(monkeypatch)

    assert svc.run_all_jobs_matching_cycle(str(uuid.uuid4()), limit=500, terms=None) == 0
    assert "urls" not in captured


# ── The preferences endpoint ─────────────────────────────────────────────────

def test_roles_save_without_a_level_and_read_back_from_postgres(uid, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.deps import CurrentUser, get_current_user
    from backend.main import app

    monkeypatch.setattr(
        "backend.services.all_jobs_match_service.schedule_refresh_for_user", lambda user_id: None
    )
    # The JSON file store is wiped on every Render deploy; prove the read
    # does not depend on it by making it return nothing.
    monkeypatch.setattr("backend.services.user_profile_store.load", lambda user_id: {})
    monkeypatch.setattr("backend.services.user_profile_store.save", lambda user_id, p: None)

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=uid, email="t@example.com")
    try:
        client = TestClient(app)
        saved = client.post("/api/profile/preferences", json={"roles": [{"role": "Campaign Manager"}]})
        read = client.get("/api/profile/preferences")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert saved.status_code == 200, saved.text
    assert read.json()["target_titles"] == ["Campaign Manager"]
    assert read.json()["roles"] == [{"role": "Campaign Manager", "seniority": ""}]


def test_bridge_skips_a_role_the_user_already_has_under_another_url(catalog, monkeypatch):
    """
    The same role (title, company, location) re-posted under a new URL must not
    count as new. It used to: save then deduped it onto the existing posting
    and inserted nothing, so the same duplicates filled every cycle's limit and
    real new jobs were never reached.
    """
    from backend.services import all_jobs_match_service as svc
    from backend.repositories.job_repository import canonical_dedup_key

    monkeypatch.setattr(svc, "_existing_job_ids", lambda user_id: set())
    monkeypatch.setattr(
        svc, "_existing_posting_keys",
        lambda user_id: {canonical_dedup_key("Digital Marketing Manager", "Acme", "Unknown")},
    )
    captured = _capture_saves(monkeypatch)
    svc.run_all_jobs_matching_cycle(str(uuid.uuid4()), limit=500, terms=["Digital Marketing"])
    assert catalog["marketing"] not in captured.get("urls", [])


# ── Returning users are recognised, not sent back through onboarding ────────

def test_saved_level_round_trips_and_returning_user_reads_as_onboarded(uid, monkeypatch):
    """
    The Google sign-in callback asks /api/auth/sync-user whether this user
    already finished onboarding; until it did, every Google login landed on
    the "complete your profile" page. Pin both halves: roles keep their level
    in Postgres, and an onboarded user is reported as completed.
    """
    from fastapi.testclient import TestClient
    from backend.api.deps import CurrentUser, get_current_user
    from backend.main import app
    from backend.repositories import profile_repository

    monkeypatch.setattr(
        "backend.services.all_jobs_match_service.schedule_refresh_for_user", lambda user_id: None
    )
    monkeypatch.setattr("backend.services.user_profile_store.load", lambda user_id: {})
    monkeypatch.setattr("backend.services.user_profile_store.save", lambda user_id, p: None)

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=uid, email=f"{uid}@example.com")
    try:
        client = TestClient(app)
        assert client.post(
            "/api/profile/preferences", json={"roles": [{"role": "Insurance Agent", "seniority": "senior"}]},
        ).status_code == 200
        profile_repository.mark_onboarding_complete(uid)
        read = client.get("/api/profile/preferences").json()
        sync = client.post("/api/auth/sync-user")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert read["roles"] == [{"role": "Insurance Agent", "seniority": "senior"}]
    assert sync.status_code == 200, sync.text
    assert sync.json()["profile_completed"] is True


# ── Titles saved in the other places the product writes them ────────────────
# Production, 2026-10-28: users with a role saved through Ariel, or a CV
# stored in cv_claims, had no search terms — source_titles read only
# role_preferences and cv_data.

def test_roles_told_to_ariel_count_as_picked_roles():
    profile = {"career_goals": {"target_roles": ["Insurance Agent"]},
               "experience": [{"role": "Barista"}]}
    assert utt.source_titles(profile) == ["Insurance Agent"]


def test_onboarding_roles_still_win_over_ariel_goals():
    profile = {"role_preferences": {"target_titles": ["Nurse"]},
               "career_goals": {"target_roles": ["Teacher"]}}
    assert utt.source_titles(profile) == ["Nurse"]


def test_cv_stored_in_cv_claims_gives_titles():
    profile = {"experience": [{"role": "Pension Advisor", "company": "X"}, {"title": "Clerk"}]}
    assert utt.source_titles(profile) == ["Pension Advisor", "Clerk"]


def test_malformed_goals_do_not_crash():
    assert utt.source_titles({"career_goals": "oops", "role_preferences": None}) == []


def test_cv_claims_profile_gets_terms_from_postgres(uid, monkeypatch):
    """End to end through the real profile read: a CV saved the current way."""
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository

    with Session(ENGINE) as s:
        row, _ = profile_repository.get_or_create(s, uid, now=datetime.now(timezone.utc).isoformat())
        mp = dict(row.master_profile or {})
        mp["experience"] = [{"role": "Insurance Agent", "company": "Harel"}]
        row.master_profile = mp
        profile_repository.save(s, row)
        s.commit()

    assert utt.source_titles(utt._profile(uid)) == ["Insurance Agent"]


# ── CVs saved empty before #55 ────────────────────────────────────────────────
# Production, 2026-10-29: two onboarded users had a cv_documents row and a
# cv_data answer whose experiences list was empty — uploads from before
# 2026-10-16, when an unreadable file was saved as an empty success. They got
# no search terms and no signal to upload again.

def test_cv_with_no_experience_needs_reupload():
    profile = {"cv_imported_at": "2026-10-14T19:25:05+00:00", "cv_data": {"experiences": [], "skills": []}}
    assert utt.cv_needs_reupload(profile) is True


def test_readable_cv_does_not_need_reupload():
    assert utt.cv_needs_reupload({"cv_data": {"experiences": [{"role": "Nurse"}]}}) is False
    assert utt.cv_needs_reupload({"cv_imported_at": "x", "experience": [{"role": "Nurse"}]}) is False


def test_user_without_a_cv_is_not_asked_to_reupload():
    assert utt.cv_needs_reupload({}) is False
    assert utt.cv_needs_reupload({"cv_data": {}}) is False


def _get_preferences(uid: str, monkeypatch) -> dict:
    from fastapi.testclient import TestClient
    from backend.api.deps import CurrentUser, get_current_user
    from backend.main import app

    monkeypatch.setattr("backend.services.user_profile_store.load", lambda user_id: {})
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=uid, email="t@example.com")
    try:
        res = TestClient(app).get("/api/profile/preferences")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert res.status_code == 200, res.text
    return res.json()


def _save_cv(uid: str, *, cv_data: dict, experience: list) -> None:
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository
    now = datetime.now(timezone.utc).isoformat()
    with Session(ENGINE) as s:
        row, _ = profile_repository.get_or_create(s, uid, now=now)
        mp = dict(row.master_profile or {})
        mp["cv_data"] = cv_data
        mp["experience"] = experience
        mp["cv_imported_at"] = now
        row.master_profile = mp
        profile_repository.save(s, row)
        s.commit()


def test_preferences_flag_an_empty_saved_cv(uid, monkeypatch):
    """The production shape, through the real Postgres read and the route."""
    _save_cv(uid, cv_data={"experiences": [], "skills": [], "education": [], "summary": ""}, experience=[])
    assert _get_preferences(uid, monkeypatch)["cv_unreadable"] is True


def test_preferences_do_not_flag_a_readable_cv(uid, monkeypatch):
    _save_cv(uid, cv_data={"experiences": []}, experience=[{"role": "Insurance Agent", "company": "Harel"}])
    assert _get_preferences(uid, monkeypatch)["cv_unreadable"] is False


def test_preferences_do_not_flag_a_user_with_no_cv(uid, monkeypatch):
    _set_roles(uid, ["Nurse"])
    assert _get_preferences(uid, monkeypatch)["cv_unreadable"] is False


# ── Degrees and military service are not jobs to search for ──────────────────
# Production, 2026-10-28: the founder's CV gave the search terms
# "B.A. Business Administration & Digital Innovation" and "Clerk to Lieutenant
# Colonel" — the parser files both under experiences.

def test_degree_and_military_entries_are_skipped_for_search_terms():
    profile = {"experience": [
        {"role": "B.A. Business Administration & Digital Innovation", "company": "Reichman University"},
        {"role": "Insurance & Financial Referent", "company": "Harel"},
        {"role": "Clerk to Lieutenant Colonel", "company": "IDF"},
        {"role": "Customer Success Manager", "company": "Monday"},
        {"role": "Operations Coordinator", "company": "Wix"},
    ]}
    assert utt.source_titles(profile) == [
        "Insurance & Financial Referent", "Customer Success Manager", "Operations Coordinator",
    ]


@pytest.mark.parametrize("title,company", [
    ("BSc Computer Science", ""), ("MBA", "Tel Aviv University"), ("Master of Laws", ""),
    ("תואר ראשון במנהל עסקים", ""), ("Bachelor's degree in Economics", ""),
])
def test_a_degree_is_never_a_job(title, company):
    assert utt.source_titles({"experience": [{"role": title, "company": company}]}) == []


MILITARY_ROLES = [
    ("Logistics NCO", "IDF"), ("Clerk", 'צה"ל'), ("Operations Sergeant", ""),
    ("פקידת לשכה", "צה״ל"), ("מש\"קית ת\"ש", "שירות סדיר"), ("Instructor", "Israeli Air Force"),
]


@pytest.mark.parametrize("title,company", MILITARY_ROLES)
def test_military_service_gives_way_to_civilian_jobs(title, company):
    profile = {"experience": [{"role": title, "company": company},
                              {"role": "Customer Success Manager", "company": "Monday"}]}
    assert utt.source_titles(profile) == ["Customer Success Manager", title]


def test_army_tech_career_still_gets_search_terms():
    """A developer whose roles so far were in an army tech unit: those roles are
    the career. With nothing civilian, military roles are used (they used to be
    dropped, leaving such a user with no search terms at all)."""
    profile = {"experience": [
        {"role": "Development Team Lead", "company": "Ofek unit, IAF", "kind": "military"},
        {"role": "DB And BI Developer", "company": "Ofek unit, IAF", "kind": "military"},
    ]}
    assert utt.source_titles(profile) == ["Development Team Lead", "DB And BI Developer"]


@pytest.mark.parametrize("title,company", [
    ("Manager", "Leumi"), ("Marketing Associate", ""), ("Sales Associate", "Old Navy"),
    ("Data Analyst", "Mabat"), ("Deputy Manager", ""), ("סגן מנהל סניף", "בנק הפועלים"),
    ("Master Data Specialist", "Teva"), ("Business Analyst", "Amdocs"),
])
def test_real_jobs_are_kept(title, company):
    assert utt.source_titles({"experience": [{"role": title, "company": company}]}) == [title]


def test_picked_roles_are_never_filtered():
    """The filter is for guessing from a CV; a role the user chose is kept as is."""
    profile = {"role_preferences": {"target_titles": ["Military Liaison Officer"]}}
    assert utt.source_titles(profile) == ["Military Liaison Officer"]
