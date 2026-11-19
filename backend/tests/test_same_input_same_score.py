"""
The same input keeps the score it got the first time.

Two model calls fed every score, and neither repeated itself at
temperature 0: the JD parser rewrote the same ad differently on each
scoring, and the scorer moved a partial fit by up to 10 points on the same
prompt (docs/research/07-benchmark-results.md). Now the first parse of an
ad and the first valid answer to a prompt are kept and reused; a changed
input makes a new prompt and a new answer. Every scoring is a row in
shadow_match_scores, the score history.

Pure tests: the model is faked; the history lookup runs on in-memory SQLite.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine

from backend.agents import jd_parser
from backend.core.database import Base
from backend.repositories import shadow_score_repository as repo
from backend.services import match_score_service as svc
from backend.services.llm_client import LLMResult


def _reply(payload, model="test-model") -> LLMResult:
    return LLMResult(text=json.dumps(payload), model=model, input_tokens=None,
                     output_tokens=None, latency_ms=0.0, attempts=1, raw=None)


# ── JD parser ─────────────────────────────────────────────────────────────────

async def test_the_same_ad_is_parsed_once(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(jd_parser, "_cached_parse", lambda k: store.get(k))
    monkeypatch.setattr(jd_parser, "_store_parse", lambda k, v: store.__setitem__(k, v))
    fake = AsyncMock(return_value=_reply({"role_title": "Analyst", "must_haves": ["SQL"]}))
    ad = "Data Analyst at Acme. Must have SQL. " * 20
    with patch.object(jd_parser, "call_llm", new=fake):
        first = await jd_parser.JDParserAgent().parse_and_format_jd(ad)
        again = await jd_parser.JDParserAgent().parse_and_format_jd(ad)
        other = await jd_parser.JDParserAgent().parse_and_format_jd(ad + " Python too.")
    assert fake.await_count == 2                   # the repeat was not sent
    assert first.formatted_text == again.formatted_text
    assert fake.call_args_list[0].kwargs["temperature"] == 0.0
    assert other.formatted_text                    # a changed ad is parsed afresh


async def test_a_broken_parse_is_not_kept(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(jd_parser, "_cached_parse", lambda k: store.get(k))
    monkeypatch.setattr(jd_parser, "_store_parse", lambda k, v: store.__setitem__(k, v))
    bad = LLMResult(text="not json", model="m", input_tokens=None, output_tokens=None,
                    latency_ms=0.0, attempts=1, raw=None)
    with patch.object(jd_parser, "call_llm", new=AsyncMock(return_value=bad)):
        await jd_parser.JDParserAgent().parse_and_format_jd("Some ad text " * 30)
    assert store == {}


# ── Scorer ────────────────────────────────────────────────────────────────────

_ANSWER = {"semantic_score": 62, "management_score": 40, "fit_brief": "ok",
           "missing_critical_capabilities": [], "requirements": []}
_CV = {"experience": [{"role": "Analyst", "company": "Acme", "dates": "2021 - present",
                       "bullets": ["Built the weekly KPI report"]}]}


def _history(monkeypatch):
    """Stand-in for shadow_match_scores: rows of {prompt_hash, answer, model}."""
    rows: list[dict] = []

    def first(user_id, prompt_hash):
        hit = next((r for r in rows if r["prompt_hash"] == prompt_hash), None)
        return (hit["answer"], hit["model"]) if hit else None

    monkeypatch.setattr(repo, "first_answer", first)
    return rows


async def test_the_same_prompt_keeps_its_first_answer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("MATCH_SCORE_REUSE", raising=False)
    rows = _history(monkeypatch)
    fake = AsyncMock(side_effect=[_reply(_ANSWER), _reply({**_ANSWER, "semantic_score": 48})])
    with patch.object(svc, "call_llm", new=fake):
        t1: dict = {}
        s1 = await svc._llm_dual_score(_CV, "jd " * 200, "Analyst", user_id="u1", trace=t1)
        rows.append(t1)
        t2: dict = {}
        s2 = await svc._llm_dual_score(_CV, "jd " * 200, "Analyst", user_id="u1", trace=t2)
    assert fake.await_count == 1
    assert s1[0] == s2[0] == 62.0
    assert t1["reused"] is False and t2["reused"] is True
    assert t1["prompt_hash"] == t2["prompt_hash"]
    assert t2["model"] == "test-model"             # who answered first


async def test_a_changed_profile_is_scored_again(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("MATCH_SCORE_REUSE", raising=False)
    rows = _history(monkeypatch)
    fake = AsyncMock(side_effect=[_reply(_ANSWER), _reply({**_ANSWER, "semantic_score": 80})])
    changed = {"experience": [*_CV["experience"],
                              {"role": "Intern", "company": "Beta", "dates": "2020 - 2021"}]}
    with patch.object(svc, "call_llm", new=fake):
        t1: dict = {}
        await svc._llm_dual_score(_CV, "jd " * 200, "Analyst", user_id="u1", trace=t1)
        rows.append(t1)
        s2 = await svc._llm_dual_score(changed, "jd " * 200, "Analyst", user_id="u1", trace={})
    assert fake.await_count == 2
    assert s2[0] == 80.0


async def test_reuse_can_be_turned_off_to_measure_the_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("MATCH_SCORE_REUSE", "0")
    rows = _history(monkeypatch)
    fake = AsyncMock(side_effect=[_reply(_ANSWER), _reply(_ANSWER)])
    with patch.object(svc, "call_llm", new=fake):
        t1: dict = {}
        await svc._llm_dual_score(_CV, "jd " * 200, "Analyst", user_id="u1", trace=t1)
        rows.append(t1)
        await svc._llm_dual_score(_CV, "jd " * 200, "Analyst", user_id="u1", trace={})
    assert fake.await_count == 2


async def test_a_fallback_is_never_recorded_as_an_answer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    _history(monkeypatch)
    bad = LLMResult(text="{not json", model="m", input_tokens=None, output_tokens=None,
                    latency_ms=0.0, attempts=1, raw=None)
    trace: dict = {}
    with patch.object(svc, "call_llm", new=AsyncMock(return_value=bad)):
        out = await svc._llm_dual_score(_CV, "jd " * 200, "Analyst", user_id="u1", trace=trace)
    assert out[0] == 60.0 and trace == {}


# ── The history lookup itself ─────────────────────────────────────────────────

def test_first_answer_returns_the_oldest_row_for_that_user_and_prompt():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[repo.ShadowScoreRow.__table__])

    def add(user, h, answer):
        repo.insert(user_id=user, job_title="t", company="c", existing_score=0.0,
                    ats_score=0.0, created_at="2026-11-18",
                    breakdown_json=json.dumps({"prompt_hash": h, "answer": answer, "model": "m"}),
                    engine=eng)

    add("u1", "aaa", "first")
    add("u1", "aaa", "second")
    add("u2", "bbb", "someone else's")
    add("u1", "ccc", "")                          # no answer recorded: not reusable
    assert repo.first_answer("u1", "aaa", engine=eng) == ("first", "m")
    assert repo.first_answer("u1", "bbb", engine=eng) is None
    assert repo.first_answer("u1", "ccc", engine=eng) is None
