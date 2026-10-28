"""
All Jobs title search: one substring match on the whole query found almost
nothing for "מנהל מוצר" — not "Product Manager", not "מנהלת מוצר", not
"Manager, Product". The query now expands into variants (services/title_search.py)
and a title matches when it contains every word of one variant.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from backend.services.title_search import expand_title_query

ROOT = Path(__file__).resolve().parents[2]


def _matches(title: str, query: str) -> bool:
    from backend.services.title_search import title_matches
    return title_matches(title, query)


@pytest.mark.parametrize("title", [
    "Product Manager",
    "Senior Product Manager - Payments",
    "Digital Product Manager",
    "מנהל/ת מוצר",
    "מנהלת מוצר טכנולוגי",
    "Manager, Product Growth",
])
def test_hebrew_query_finds_both_languages_and_similar_titles(title):
    assert _matches(title, "מנהל מוצר")


@pytest.mark.parametrize("title", ["מנהל/ת מוצר", "מנהל מוצר דיגיטלי", "Product Manager"])
def test_english_query_finds_hebrew_titles(title):
    assert _matches(title, "Product Manager")


@pytest.mark.parametrize("title", ["Production Manager", "Marketing Manager", "מנהל ייצור"])
def test_unrelated_titles_do_not_match(title):
    assert not _matches(title, "Product Manager")


def test_feminine_query_and_plural():
    assert _matches("אנליסט/ית נתונים", "אנליסטית נתונים")
    assert _matches("Data Analyst", "data analysts")


def test_developer_and_engineer_are_interchangeable():
    assert _matches("Backend Developer", "backend engineer")


def test_blank_query():
    assert expand_title_query("   ") == []


def test_sql_ors_variants_and_ands_words():
    from backend.repositories.all_jobs_repository import AllJobsFilters, _build_filter_conditions
    [cond] = _build_filter_conditions(AllJobsFilters(title="מנהל מוצר"))
    sql = str(cond.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert " OR " in sql and " AND " in sql
    assert "~*" in sql and "product" in sql      # English: whole-word regex
    assert "%מנהל%" in sql                        # Hebrew: substring


def test_like_wildcards_are_literal():
    from backend.repositories.all_jobs_repository import _escape_like, _title_word_condition
    assert _escape_like("100%_x") == "100\\%\\_x"
    sql = str(_title_word_condition("c++").compile(dialect=postgresql.dialect()))
    assert "ILIKE" in sql and "ESCAPE" in sql


def test_backend_catalog_matches_frontend_catalog():
    ts = (ROOT / "frontend/src/lib/roleCatalog.ts").read_text(encoding="utf-8")
    body = ts[ts.index("export const ROLE_CATALOG"):]
    body = body[:body.index("\n]")]
    pairs = re.findall(r"\{\s*en:\s*'((?:[^'\\]|\\.)*)'\s*,\s*he:\s*'((?:[^'\\]|\\.)*)'\s*\}", body)
    assert pairs, "parsed nothing from roleCatalog.ts — the check would be meaningless"
    frontend = [{"en": e.replace("\\'", "'"), "he": h.replace("\\'", "'")} for e, h in pairs]
    backend = json.loads((ROOT / "backend/services/role_catalog.json").read_text(encoding="utf-8"))["roles"]
    assert backend == frontend, "regenerate backend/services/role_catalog.json from roleCatalog.ts"
