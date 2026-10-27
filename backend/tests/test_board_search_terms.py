"""
The job boards search every user's own roles, and each job reaches only the
users it fits.

Until this existed, Drushim / AllJobs / Gotfriends / Dialog / Nisha and Google
Dork searched only config.TARGET_SEARCH_QUERIES — the founder's Product / CS /
Ops roles — so an insurance agent who picked "סוכן ביטוח" in onboarding was
never searched for, and the global gate threw away the rest.

These tests pin: the union of users' terms (no duplicates, covered terms
dropped), the per-cycle cap and rotation (Hebrew first for the boards), the
global-list fallback, and per-user delivery — the insurance-agent job goes to
the insurance agent and not to the product manager. They also pin that the
cycle makes no LLM call.
"""
import uuid

import pytest
from sqlalchemy import text

from backend.config import TARGET_SEARCH_QUERIES
from backend.scrapers.base_scraper import minimal_job_match
from backend.scrapers.relevancy import is_title_relevant
from backend.services import board_discovery as bd
from backend.services import board_search_terms as bst

INSURANCE = ["סוכן ביטוח", "סוכנת ביטוח", "Insurance Agent"]
PRODUCT = ["Product Manager", "מנהל מוצר"]


# ── Union ────────────────────────────────────────────────────────────────────

def test_union_removes_duplicates_across_users_and_spellings():
    union = bst.union_terms({
        "a": ["Product Manager", "מנהל/ת מוצר"],
        "b": ["product manager", "מנהל מוצר", "Insurance Agent"],
    })
    assert [t.lower() for t in union].count("product manager") == 1
    # "מנהל/ת מוצר" and "מנהל מוצר" are the same search once the gendered
    # suffix is normalised away.
    assert len([t for t in union if "מוצר" in t]) == 1
    assert "Insurance Agent" in union


def test_union_drops_terms_a_shorter_phrase_already_covers():
    union = bst.union_terms({"a": ["Senior Product Manager", "Product Manager"]})
    assert union == ["Product Manager"]


def test_a_single_word_never_swallows_specific_roles():
    union = bst.union_terms({"a": ["Manager", "Product Manager"]})
    assert set(union) == {"Manager", "Product Manager"}


def test_union_interleaves_users_so_a_cap_reaches_everyone():
    union = bst.union_terms({
        "a": ["Product Manager", "Product Owner", "Head of Product"],
        "b": ["Insurance Agent", "Pension Advisor"],
    })
    assert union[:2] == ["Product Manager", "Insurance Agent"]


# ── Cap and rotation ─────────────────────────────────────────────────────────

def test_short_list_is_returned_whole():
    assert bst.select_for_cycle(["a", "b"], cap=10, cycle=7) == ["a", "b"]


def test_cap_holds_and_rotation_covers_every_term():
    terms = [f"term {i}" for i in range(23)]
    seen: set[str] = set()
    for cycle in range(3):
        chosen = bst.select_for_cycle(terms, cap=10, cycle=cycle)
        assert len(chosen) == 10
        seen.update(chosen)
    assert seen == set(terms)


def test_hebrew_terms_get_priority_on_the_boards():
    terms = [f"English {i}" for i in range(10)] + ["סוכן ביטוח", "אחות", "מורה"]
    chosen = bst.select_for_cycle(terms, cap=4, cycle=0, hebrew_share=0.7)
    assert len(chosen) == 4
    assert {"סוכן ביטוח", "אחות", "מורה"} <= set(chosen)


def test_unused_hebrew_slots_go_to_english():
    terms = [f"English {i}" for i in range(12)]
    assert len(bst.select_for_cycle(terms, cap=10, cycle=0, hebrew_share=0.7)) == 10


def test_zero_cap_searches_nothing():
    assert bst.select_for_cycle(["a"], cap=0, cycle=0) == []


# ── Planning a cycle ─────────────────────────────────────────────────────────

def test_cycle_searches_the_users_terms_not_the_global_list():
    keywords, _ = bd.plan_cycle(
        ["agent", "pm"], {"agent": INSURANCE, "pm": PRODUCT},
        cap=10, cycle=0, hebrew_share=0.7,
    )
    assert "סוכן ביטוח" in keywords and "Product Manager" in keywords
    assert "Customer Success" not in keywords          # a global-list-only term


def test_no_cached_terms_at_all_falls_back_to_the_global_list():
    keywords, matchers = bd.plan_cycle(["x"], {}, cap=100, cycle=0, hebrew_share=0.7)
    norm = {bst._key(t) for t in TARGET_SEARCH_QUERIES}
    assert keywords and all(bst._key(k) in norm for k in keywords)
    assert matchers["x"] is is_title_relevant


def test_cycle_respects_the_cap():
    many = {f"u{i}": [f"Role {i} Specialist", f"תפקיד {i}"] for i in range(30)}
    keywords, _ = bd.plan_cycle(list(many), many, cap=10, cycle=0, hebrew_share=0.7)
    assert len(keywords) == 10


# ── Delivery: a job reaches only the users it fits ───────────────────────────

def _job(title: str, n: int):
    return minimal_job_match(
        job_id=f"j{n}", title=title, company="Acme", location="Tel Aviv",
        apply_url=f"https://board.example/{n}", jd_text="",
    )


def test_insurance_job_reaches_the_insurance_agent_not_the_product_manager():
    _, matchers = bd.plan_cycle(
        ["agent", "pm"], {"agent": INSURANCE, "pm": PRODUCT},
        cap=10, cycle=0, hebrew_share=0.7,
    )
    jobs = [_job("סוכן/ת ביטוח לסוכנות בתל אביב", 1), _job("Senior Product Manager", 2)]
    calls: dict[str, list[str]] = {}

    def fake_save(mine, limit, user_id, matcher):
        calls[user_id] = [j.title for j in mine]
        return len(mine)

    saved = bd.distribute(jobs, matchers, per_user_limit=20, save=fake_save)
    assert calls["agent"] == ["סוכן/ת ביטוח לסוכנות בתל אביב"]
    assert calls["pm"] == ["Senior Product Manager"]
    assert saved == {"agent": 1, "pm": 1}


def test_per_user_limit_is_passed_to_the_save():
    _, matchers = bd.plan_cycle(["pm"], {"pm": PRODUCT}, cap=10, cycle=0, hebrew_share=0.7)
    limits = []
    bd.distribute(
        [_job("Product Manager", i) for i in range(5)], matchers, per_user_limit=3,
        save=lambda mine, limit, user_id, matcher: limits.append(limit) or min(limit, len(mine)),
    )
    assert limits == [3]


def test_boards_are_interleaved_and_urls_deduplicated():
    a = [_job("Product Manager", 1), _job("Product Manager", 2)]
    b = [_job("Product Manager", 3), _job("Product Manager", 1)]
    out = bd._interleave([a, b])
    assert [j.apply_url.rsplit("/", 1)[1] for j in out] == ["1", "3", "2"]


# ── The whole cycle, with fake boards ────────────────────────────────────────

class _FakeBoard:
    instances: list = []

    def __init__(self, keywords, user_id, title_filter, max_jobs=20):
        self.keywords, self.title_filter, self._max_jobs = keywords, title_filter, max_jobs
        _FakeBoard.instances.append(self)

    async def fetch_jobs(self):
        cards = ["סוכן ביטוח", "Product Manager", "Forklift Driver"]
        # The real scrapers apply title_filter before any detail fetch.
        return [_job(t, i) for i, t in enumerate(cards) if self.title_filter(t)]


async def test_full_cycle_searches_union_and_delivers_per_user(monkeypatch):
    _FakeBoard.instances = []
    monkeypatch.setattr("backend.config.BOARD_DISCOVERY_ENABLED", True)
    monkeypatch.setattr(
        "backend.services.user_title_terms.cached_terms_for_users",
        lambda ids: {"agent": INSURANCE, "pm": PRODUCT},
    )
    monkeypatch.setattr(bst, "next_cycle", lambda key: 0)

    async def _no_llm(**kw):
        raise AssertionError("board discovery must not call the LLM")
    monkeypatch.setattr("backend.services.llm_client.call_llm", _no_llm)

    delivered: dict[str, list[str]] = {}

    def fake_save(mine, limit, user_id, matcher):
        delivered[user_id] = [j.title for j in mine]
        return len(mine)
    monkeypatch.setattr("backend.scrapers.scraper_manager.ScraperManager._save_new", staticmethod(fake_save))

    saved = await bd.run_board_discovery_cycle(
        ["agent", "pm"], respect_interval=False, scraper_classes=[_FakeBoard, _FakeBoard],
    )

    assert len(_FakeBoard.instances) == 2
    kw = _FakeBoard.instances[0].keywords
    assert "סוכן ביטוח" in kw and "Product Manager" in kw and len(kw) <= 10
    assert delivered == {"agent": ["סוכן ביטוח"], "pm": ["Product Manager"]}
    assert saved == {"agent": 1, "pm": 1}


def test_board_discovery_is_off_by_default():
    # Every board answered Render's IP with 403 on the first production cycle.
    from backend import config
    assert config.BOARD_DISCOVERY_ENABLED is False


async def test_paused_cycle_sends_no_board_request(monkeypatch):
    _FakeBoard.instances = []
    monkeypatch.setattr("backend.config.BOARD_DISCOVERY_ENABLED", False)

    def _no_db(ids):
        raise AssertionError("a paused cycle must not even read terms")
    monkeypatch.setattr("backend.services.user_title_terms.cached_terms_for_users", _no_db)

    # The manual "sync" path (respect_interval=False) is paused too.
    assert await bd.run_board_discovery_cycle(
        ["agent"], respect_interval=False, scraper_classes=[_FakeBoard],
    ) == {}
    assert _FakeBoard.instances == []


async def test_no_terms_never_becomes_an_empty_board_search(monkeypatch):
    _FakeBoard.instances = []
    monkeypatch.setattr("backend.config.BOARD_DISCOVERY_ENABLED", True)
    monkeypatch.setattr("backend.services.user_title_terms.cached_terms_for_users", lambda ids: {})
    monkeypatch.setattr(bst, "next_cycle", lambda key: 0)
    monkeypatch.setattr(bd, "plan_cycle", lambda *a, **k: ([], {"agent": lambda t: True}))
    assert await bd.run_board_discovery_cycle(
        ["agent"], respect_interval=False, scraper_classes=[_FakeBoard],
    ) == {}
    assert _FakeBoard.instances == []


async def test_no_pipeline_users_runs_nothing(monkeypatch):
    _FakeBoard.instances = []
    monkeypatch.setattr("backend.config.BOARD_DISCOVERY_ENABLED", True)
    monkeypatch.setattr("backend.services.tenant_registry.list_pipeline_user_ids", lambda: [])
    assert await bd.run_board_discovery_cycle(scraper_classes=[_FakeBoard]) == {}
    assert _FakeBoard.instances == []


async def test_dork_searches_the_users_own_terms(monkeypatch):
    from backend.services import discovery
    monkeypatch.setattr(
        "backend.services.user_title_terms.cached_terms_for_users", lambda ids: {"agent": INSURANCE},
    )
    monkeypatch.setattr(bst, "next_cycle", lambda key: 0)
    keywords, relevant = discovery._dork_terms_for("agent")
    assert keywords == INSURANCE
    assert relevant("סוכנת ביטוח בכירה") and not relevant("Product Manager")


async def test_dork_cap_is_eight_terms(monkeypatch):
    from backend.services import discovery
    monkeypatch.setattr("backend.services.user_title_terms.cached_terms_for_users", lambda ids: {})
    monkeypatch.setattr(bst, "next_cycle", lambda key: 0)
    keywords, relevant = discovery._dork_terms_for("nobody")
    assert len(keywords) == 8                       # global list, capped
    assert relevant is is_title_relevant


# ── The narrow batch read (Postgres) ─────────────────────────────────────────

@pytest.fixture()
def two_users(db_available):
    import json
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository
    from sqlalchemy.orm import Session
    from datetime import datetime, timezone

    ids = [str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())]
    with Session(ENGINE) as s:
        for u in ids:
            profile_repository.get_or_create(s, u, now=datetime.now(timezone.utc).isoformat())
        s.commit()
    with ENGINE.begin() as c:
        for u, terms in zip(ids[:2], (INSURANCE, PRODUCT)):
            c.execute(
                text("""INSERT INTO public.profile_answers (user_id, question_id, answer, updated_at)
                        VALUES (CAST(:u AS uuid), 'title_search_terms', CAST(:a AS jsonb), now())"""),
                {"u": u, "a": json.dumps({"source_hash": "x", "terms": terms})},
            )
    yield ids
    with ENGINE.begin() as c:
        for u in ids:
            c.execute(text("DELETE FROM public.profile_answers WHERE user_id = CAST(:u AS uuid)"), {"u": u})
            c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": u})


def test_batch_read_returns_each_users_terms_and_skips_users_without(two_users):
    from backend.services.user_title_terms import cached_terms_for_users
    out = cached_terms_for_users(two_users)
    assert out == {two_users[0]: INSURANCE, two_users[1]: PRODUCT}
