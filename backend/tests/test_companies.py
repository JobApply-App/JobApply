"""
Phase 1 of docs/research/09-companies-and-costs.md: one company normalizer,
the companies / company_aliases tables, and source precedence.

Runs against a throwaway in-memory SQLite engine, never the app database.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.models.company import CompanyAliasRow, CompanyRow
from backend.repositories import company_repository as repo
from backend.services.company_identity import company_key, linkedin_slug

LOGO = "https://media.licdn.com/dms/image/x/company-logo_100_100/0/1?e=2147483647"
LOGO2 = "https://media.licdn.com/dms/image/y/company-logo_100_100/0/2?e=2147483647"


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    CompanyRow.__table__.create(eng)
    CompanyAliasRow.__table__.create(eng)
    return eng


# ── Normalizer ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b", [
    ("Wix", "Wix.com"),
    ("Wiz", "Wiz (a Google Company)"),
    ("monday.com", "Monday"),
    ("Nova Ltd.", "NOVA"),
    ("Vishay Precision Group, Inc. (VPG)", "Vishay Precision Group"),
    ('חברת החשמל בע"מ', "חברת החשמל"),
    ("Corephotonics Ltd", "corephotonics"),
])
def test_same_company(a, b):
    assert company_key(a) == company_key(b)


def test_hebrew_is_kept_not_erased():
    # The culture normalizer this replaces turned every Hebrew name into "".
    assert company_key("איחוד הצלה") == "איחוד הצלה"
    assert company_key("Discount Bank בנק דיסקונט") == "discount bank בנק דיסקונט"


@pytest.mark.parametrize("a, b", [
    ("Strauss Group", "Strauss Water"),
    ("Elbit Systems", "Elbit Imaging"),
])
def test_different_companies_stay_different(a, b):
    assert company_key(a) != company_key(b)


def test_empty_names():
    assert company_key(None) is None
    assert company_key("  ( ) ") is None
    assert company_key("Ltd") is None


def test_short_legal_form_only_dropped_at_the_end():
    assert company_key("Co Hub") == "co hub"
    assert company_key("Acme Co") == "acme"


def test_linkedin_slug():
    assert linkedin_slug("https://il.linkedin.com/company/wix-com?trk=public") == "wix-com"
    assert linkedin_slug("https://www.linkedin.com/company/Recon-Engineering-%26-Construction/") == "recon-engineering-&-construction"
    assert linkedin_slug("https://example.com/about") is None
    assert linkedin_slug(None) is None


# ── Identity and aliases ──────────────────────────────────────────────────────

def _listing(session, name, url=None, logo=None, industries=None, source="linkedin"):
    return repo.upsert_listing(session, name=name, company_url=url, logo_url=logo, industries=industries, source=source)


def test_one_linkedin_page_is_one_company_across_spellings(engine):
    with Session(engine) as s:
        a = _listing(s, "Nisha - נישה", "https://il.linkedin.com/company/nisha-group")
        b = _listing(s, "Nisha Group - קבוצת נישה", "https://il.linkedin.com/company/nisha-group?trk=x")
        s.commit()
        assert a.id == b.id
        assert s.query(CompanyRow).count() == 1
        assert s.query(CompanyAliasRow).count() == 2


def test_name_without_page_joins_the_company_by_alias(engine):
    with Session(engine) as s:
        a = _listing(s, "Wix", "https://il.linkedin.com/company/wix-com", logo=LOGO)
        b = _listing(s, "Wix.com")               # e.g. a job_postings name, no URL
        s.commit()
        assert a.id == b.id


def test_same_name_on_two_pages_is_two_companies(engine):
    with Session(engine) as s:
        a = _listing(s, "Horizon", "https://www.linkedin.com/company/horizon-il")
        b = _listing(s, "Horizon", "https://www.linkedin.com/company/horizon-us")
        s.commit()
        assert a.id != b.id
        alias = s.get(CompanyAliasRow, "horizon")
        assert alias.company_id == a.id          # the first one keeps the name


def test_page_is_learned_when_first_seen_by_name_only(engine):
    with Session(engine) as s:
        a = _listing(s, "Wix")
        b = _listing(s, "Wix", "https://il.linkedin.com/company/wix-com")
        s.commit()
        assert a.id == b.id and a.linkedin_slug == "wix-com"


def test_placeholder_or_bad_logo_is_ignored(engine):
    with Session(engine) as s:
        row = _listing(s, "Acme", logo="http://not-https/logo.png")
        s.commit()
        assert row.logo_url is None


# ── Source precedence ─────────────────────────────────────────────────────────

def test_weaker_source_never_overwrites_stronger(engine):
    with Session(engine) as s:
        _listing(s, "Acme", logo=LOGO, source="company_portal")   # a recruiter's own logo
        row = _listing(s, "Acme", logo=LOGO2, source="linkedin")  # the next scrape
        s.commit()
        assert row.logo_url == LOGO and row.logo_source == "company_portal"


def test_equal_or_stronger_source_updates(engine):
    with Session(engine) as s:
        _listing(s, "Acme", logo=LOGO, industries=["Software"])
        row = _listing(s, "Acme", logo=LOGO2, industries=["Fintech"])
        s.commit()
        assert row.logo_url == LOGO2 and row.industries == ["Fintech"]


def test_culture_attaches_to_existing_company(engine):
    with Session(engine) as s:
        _listing(s, "Wix", "https://il.linkedin.com/company/wix-com")
        s.commit()
    assert repo.attach_culture("Wix.com", {"culture_category": "scaleup"}, confidence="high", engine=engine)
    with Session(engine) as s:
        row = s.query(CompanyRow).one()
        assert row.culture == {"culture_category": "scaleup"}
        assert row.culture_confidence == "high" and row.culture_source == "jd_inferred"


def test_culture_for_a_hebrew_name_is_stored(engine):
    assert repo.attach_culture("איחוד הצלה", {"culture_category": "corporate"}, confidence="medium", engine=engine)
    assert repo.attach_culture("  ", {}, confidence=None, engine=engine) is False


# ── Logos ─────────────────────────────────────────────────────────────────────

def test_logo_found_through_any_spelling(engine):
    with Session(engine) as s:
        _listing(s, "Wiz (a Google Company)", "https://www.linkedin.com/company/wizsecurity", logo=LOGO)
        s.commit()
    assert repo.get_logos(["Wiz", "Unknown Co"], engine=engine) == {"Wiz": LOGO}


def test_upsert_listings_counts_named_rows(engine):
    rows = [
        {"company_name": "Wix", "company_url": "https://il.linkedin.com/company/wix-com", "company_logo_url": LOGO, "industries": ["Software Development"]},
        {"company_name": None, "company_url": None, "company_logo_url": None, "industries": None},
    ]
    assert repo.upsert_listings(rows, engine=engine) == 1
    assert repo.upsert_listings(rows, engine=engine) == 1        # idempotent
    with Session(engine) as s:
        assert s.query(CompanyRow).count() == 1


def test_missing_culture_is_sql_null_not_json_null(engine):
    # The first backfill stored JSON null, so "culture IS NOT NULL" counted
    # every company (2,788) instead of the 715 that have a profile.
    from sqlalchemy import text
    with Session(engine) as s:
        _listing(s, "Acme")
        s.commit()
        assert s.execute(text("select count(*) from companies where culture is null and industries is null")).scalar() == 1


# ── Phase 2 ───────────────────────────────────────────────────────────────────

from backend.services.company_identity import is_placeholder


@pytest.mark.parametrize("name", [
    "Confidential", "Confidential Careers", "Stealth AI Startup", "Undisclosed", "Private Company", "חברה חסויה",
])
def test_placeholder_names(name):
    assert is_placeholder(company_key(name))


@pytest.mark.parametrize("name", ["Stealthy Labs", "Privacy Co", "Confluent"])
def test_real_names_are_not_placeholders(name):
    assert not is_placeholder(company_key(name))


def test_placeholder_name_gets_no_company_and_no_alias(engine):
    with Session(engine) as s:
        assert repo.company_id_for(s, "Confidential") is None
        # A LinkedIn page called "Confidential" is still a page, but its name
        # must not pull every hidden employer onto it.
        row = _listing(s, "Confidential", "https://www.linkedin.com/company/confidential-career")
        s.commit()
        assert row is not None
        assert s.get(CompanyAliasRow, "confidential") is None


def test_company_id_for_reuses_the_company(engine):
    with Session(engine) as s:
        a = repo.company_id_for(s, "Wix")
        b = repo.company_id_for(s, "Wix.com")
        s.commit()
        assert a and a == b


def test_culture_key_keeps_hebrew_names():
    from backend.agents.company_culture import _company_key
    assert _company_key("Wix") == "wix"                       # unchanged: cached keys stay valid
    assert _company_key("Discount Bank בנק דיסקונט") == "discount_bank"
    assert _company_key("איחוד הצלה") == "איחוד_הצלה"         # was "", so never profiled
    assert _company_key("חברה חסויה") == ""


@pytest.mark.parametrize("finder", ["service", "dimensions"])
def test_prior_employer_by_normalized_name(finder):
    from backend.services import match_dimensions, match_score_service

    def find(exp, target):
        if finder == "service":
            return match_score_service._find_prior_employer({"experience": exp}, target)
        return match_dimensions._find_prior_employer(exp, target)

    # The CV's longer spelling: the word-boundary regex alone misses these.
    assert find([{"company": "Wix.com"}], "Wix") == "Wix.com"
    assert find([{"company": "Nova Ltd."}], "Nova") == "Nova Ltd."
    # Unchanged guarantees (CLAUDE.md principle 2).
    assert find([{"company": "River"}], "Riverside") is None
    assert find([{"company": "Elbit Systems"}], "Elbit Systems Israel") == "Elbit Systems"
    # A hidden employer is nobody's former employer.
    assert find([{"company": "Confidential"}], "Confidential") is None
