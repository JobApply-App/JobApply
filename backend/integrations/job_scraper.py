"""LinkedIn job scraper — dynamic title/location/seniority search with fit scoring.

Approach
--------
LinkedIn's public (unauthenticated) job-search pages return fully-rendered
HTML including job cards with title, company, location, and post date.
Individual job-detail pages expose a structured description block.

Both layers use plain requests + BeautifulSoup — no headless browser needed.
A small inter-request delay keeps traffic polite.  All network failures fall
back to a set of realistic simulated listings so the rest of the app always
has data to work with.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from backend.utilities.html_guard import html_visible_text, visible_text

# ── HTTP config ───────────────────────────────────────────────────────────────

_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TIMEOUT       = 12
_DETAIL_DELAY  = 0.8
_MAX_PER_QUERY = 10
_POSTED_WITHIN = "r604800"   # past 7 days

_SEARCH_BASE = "https://www.linkedin.com/jobs/search/"

# ── Seniority → LinkedIn f_E codes ───────────────────────────────────────────

SENIORITY_OPTIONS = [
    "Any level",
    "Entry Level (No experience)",
    "Junior (Some experience)",
    "Mid-Level (Experienced)",
    "Senior / Executive",
]

_SENIORITY_CODES: dict[str, str] = {
    "Entry Level (No experience)": "2",
    "Junior (Some experience)":    "3",
    "Mid-Level (Experienced)":     "4",
    "Senior / Executive":          "5,6",
}


# ── Simulated fallback data ───────────────────────────────────────────────────

_SIMULATED: list[dict[str, Any]] = [
    {
        "job_id": "sim-001",
        "title": "Associate Product Manager",
        "company": "Monday.com",
        "location": "Tel Aviv, Israel",
        "post_date": "2026-04-25",
        "url": "https://monday.com/careers",
        "description": (
            "Join Monday.com as an APM and help shape the future of work OS. "
            "You will own product areas end-to-end, write detailed PRDs, run "
            "sprint ceremonies with engineering, conduct user research, and "
            "define KPIs. Required: 1–3 years PM or PM-adjacent experience, "
            "SQL for data analysis, Jira or equivalent, Agile/Scrum, strong "
            "stakeholder management and communication skills."
        ),
        "source": "simulated",
    },
    {
        "job_id": "sim-002",
        "title": "Product Manager – Growth",
        "company": "Wix",
        "location": "Tel Aviv, Israel",
        "post_date": "2026-04-24",
        "url": "https://www.wix.com/jobs",
        "description": (
            "Drive growth initiatives at scale on Wix's self-serve funnel. "
            "Own the product roadmap for acquisition and activation features, "
            "define A/B tests, and partner with Data and Engineering. "
            "Requirements: 2+ years PM experience, SQL proficiency, product "
            "analytics tools, strong written communication, cross-functional "
            "team leadership."
        ),
        "source": "simulated",
    },
    {
        "job_id": "sim-003",
        "title": "Product Manager – B2B Platform",
        "company": "Connecteam",
        "location": "Tel Aviv-Yafo, Israel",
        "post_date": "2026-04-23",
        "url": "https://connecteam.com/careers",
        "description": (
            "Lead product development for Connecteam's deskless workforce platform. "
            "Responsibilities: roadmap ownership, writing user stories, sprint "
            "planning, customer interviews, and working with design on UX flows. "
            "Required: B2B SaaS PM experience, Jira, Agile, data-driven mindset, "
            "stakeholder management."
        ),
        "source": "simulated",
    },
    {
        "job_id": "sim-004",
        "title": "Associate Product Manager – Customer Experience",
        "company": "Fiverr",
        "location": "Tel Aviv, Israel",
        "post_date": "2026-04-22",
        "url": "https://www.fiverr.com/jobs",
        "description": (
            "Own the buyer and seller experience on Fiverr's marketplace. "
            "You'll work on discovery, onboarding, and retention flows. "
            "Requirements: product intuition, customer success background, "
            "Jira/Confluence, clear acceptance criteria, basic SQL, "
            "cross-functional collaboration skills."
        ),
        "source": "simulated",
    },
    {
        "job_id": "sim-005",
        "title": "Product Manager – Enterprise SaaS",
        "company": "Salesforce Israel",
        "location": "Tel Aviv, Israel",
        "post_date": "2026-04-21",
        "url": "https://salesforce.com/careers",
        "description": (
            "Drive enterprise product strategy for Salesforce's Israeli engineering "
            "hub. Lead roadmap planning, define OKRs, partner with solutions "
            "engineering. Required: 3+ years B2B SaaS PM experience, product strategy "
            "skills, stakeholder management, Agile/Scrum, SQL, excellent English."
        ),
        "source": "simulated",
    },
    {
        "job_id": "sim-006",
        "title": "Product Manager – Developer Tools",
        "company": "JFrog",
        "location": "Netanya, Israel (Hybrid)",
        "post_date": "2026-04-20",
        "url": "https://jfrog.com/careers",
        "description": (
            "Shape the product vision for JFrog's DevOps platform. "
            "Work closely with engineering teams on technical roadmaps, "
            "conduct market research, write detailed product specs. "
            "Requirements: technical background, Agile, Jira, product strategy, "
            "strong communication and stakeholder management."
        ),
        "source": "simulated",
    },
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get(url: str, **kwargs) -> requests.Response | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except Exception:
        return None


def _extract_job_id(urn_or_url: str) -> str:
    m = re.search(r"(\d{9,})", urn_or_url)
    return m.group(1) if m else urn_or_url


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


# ── Card-list scraper ─────────────────────────────────────────────────────────

def _scrape_cards(
    query: str,
    location: str,
    seniority_code: str = "",
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "keywords": query,
        "location": location,
        "f_TPR":    _POSTED_WITHIN,
        "position": 1,
        "pageNum":  0,
    }
    if seniority_code:
        params["f_E"] = seniority_code

    resp = _get(f"{_SEARCH_BASE}?{urlencode(params)}")
    if resp is None:
        return []

    soup  = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.base-card")[:_MAX_PER_QUERY]

    jobs: list[dict[str, Any]] = []
    for card in cards:
        title_el    = card.select_one("h3.base-search-card__title")
        company_el  = card.select_one("h4.base-search-card__subtitle")
        location_el = card.select_one("span.job-search-card__location")
        time_el     = card.select_one("time")
        link_el     = card.select_one("a.base-card__full-link")
        urn         = card.get("data-entity-urn", "")

        if not title_el:
            continue

        job_url = link_el["href"].split("?")[0] if link_el else ""
        job_id  = _extract_job_id(urn or job_url)

        jobs.append({
            "job_id":      job_id,
            "title":       _clean(title_el.get_text()),
            "company":     _clean(company_el.get_text()) if company_el else "",
            "location":    _clean(location_el.get_text()) if location_el else location,
            "post_date":   time_el.get("datetime", "") if time_el else "",
            "url":         job_url,
            "description": "",
            "source":      "linkedin",
        })

    return jobs


# ── Detail-page description fetcher ──────────────────────────────────────────

def _fetch_description(job_url: str) -> str:
    if not job_url:
        return ""
    resp = _get(job_url)
    if resp is None:
        return ""
    soup    = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one("div.show-more-less-html__markup")
    if desc_el:
        return _clean(visible_text(desc_el))
    criteria = soup.select("li.description__job-criteria-item")
    if criteria:
        return " | ".join(_clean(el.get_text()) for el in criteria)
    return ""


# ── Public: URL text extractor (for JD Matcher) ───────────────────────────────

def fetch_text_from_url(url: str, max_chars: int = 6000) -> str:
    """
    Extract readable text from any URL using requests + BeautifulSoup.
    Removes nav/footer/script noise.  Returns empty string on failure.
    """
    resp = _get(url)
    if resp is None:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = visible_text(soup, separator=" ", strip=True)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:max_chars]


# ── Public: main entry point ──────────────────────────────────────────────────

def get_latest_jobs(
    job_title: str = "Product Manager",
    location: str = "Israel",
    seniority: str = "Any level",
    fetch_descriptions: bool = True,
    max_per_query: int = _MAX_PER_QUERY,
) -> list[dict[str, Any]]:
    """
    Scrape LinkedIn for jobs matching *job_title* at *location*.

    Parameters
    ----------
    job_title   : Free-text job title to search for.
    location    : Location string passed to LinkedIn (city, country, etc.).
    seniority   : One of SENIORITY_OPTIONS.  "Any level" means no filter.
    fetch_descriptions : Whether to fetch full description from each job page.
    max_per_query      : Max results to fetch.

    Returns
    -------
    List of job dicts, each with:
        job_id, title, company, location, post_date, url, description, source

    Falls back to _SIMULATED if all network requests fail.
    """
    seniority_code = _SENIORITY_CODES.get(seniority, "")
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    cards = _scrape_cards(job_title, location, seniority_code)
    for job in cards[:max_per_query]:
        if job["job_id"] in seen_ids:
            continue
        seen_ids.add(job["job_id"])

        if fetch_descriptions and job["url"]:
            time.sleep(_DETAIL_DELAY)
            job["description"] = _fetch_description(job["url"])

        results.append(job)

    if not results:
        return _SIMULATED

    for job in results:
        if not job["description"]:
            job["description"] = f"{job['title']} at {job['company']} in {job['location']}."

    return results


# ── Fit scorer ────────────────────────────────────────────────────────────────

def _tokens(text: str) -> set[str]:
    stopwords = {"a", "an", "the", "and", "or", "of", "in", "at", "to", "for",
                 "is", "was", "as", "by", "on", "with"}
    words = re.findall(r"\b[a-z]{2,}\b", text.lower())
    return {w for w in words if w not in stopwords}


def _sim(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def score_job_fit(job: dict[str, Any], verified_profile: dict) -> dict[str, Any]:
    """
    Compute a 0-100 fit score for a job against the verified profile.

    Weights each skill match by its confidence_score, then applies a seniority
    nudge for 'senior/lead/director' or 'associate/junior' titles.
    """
    skill_records: list[dict] = verified_profile.get("skill_verification", [])
    if not skill_records:
        return {"score": 0, "matched_skills": [], "gap_skills": []}

    corpus        = f"{job.get('title', '')} {job.get('description', '')}"
    corpus_tokens = _tokens(corpus)
    total_weight  = sum(s["confidence_score"] for s in skill_records)
    earned        = 0.0
    matched: list[str] = []
    gaps:    list[str] = []

    for sr in skill_records:
        skill        = sr["skill"]
        conf         = sr["confidence_score"]
        skill_tokens = _tokens(skill)
        token_hit    = bool(skill_tokens & corpus_tokens)
        phrase_hit   = _sim(skill, corpus) >= 0.08
        if token_hit or phrase_hit:
            earned += conf
            matched.append(skill)
        else:
            gaps.append(skill)

    raw_score  = (earned / total_weight) if total_weight else 0.0
    title_low  = job.get("title", "").lower()

    if any(w in title_low for w in ("senior", "lead", "head", "director", "vp")):
        raw_score *= 0.80
    if any(w in title_low for w in ("associate", "junior", "apm")):
        raw_score = min(1.0, raw_score * 1.10)

    return {
        "score":          round(raw_score * 100),
        "matched_skills": matched,
        "gap_skills":     gaps,
    }


if __name__ == "__main__":
    import pprint
    print("Fetching live jobs…")
    jobs = get_latest_jobs(job_title="Product Manager", location="Israel", max_per_query=5)
    print(f"Found {len(jobs)} jobs.\n")
    for j in jobs:
        print(f"  [{j['post_date']}] {j['title']} @ {j['company']} ({j['source']})")
        print(f"   {j['url']}")
        print(f"   desc: {j['description'][:100]}…\n")
