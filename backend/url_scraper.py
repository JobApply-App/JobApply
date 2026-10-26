from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from backend.scrapers.ats_api_scraper import try_greenhouse_api, try_lever_api, try_workday_api
from backend.utilities.html_guard import html_visible_text, visible_text

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ── Job-title cleaning ────────────────────────────────────────────────────────

def _clean_job_title(raw: str) -> str:
    """
    Normalise a raw page/og title into a clean job title string.

    Handles the common formats produced by LinkedIn, Indeed, Glassdoor, and
    generic ATS platforms:

      LinkedIn (og:title)  "Product Analyst at Recruitx | LinkedIn"
      LinkedIn (page title) "Recruitx hiring Product Analyst JB-5141 in Tel Aviv … | LinkedIn"
      LinkedIn variant      "(3) Senior PM – Growth at Acme | LinkedIn"
      Indeed               "Product Manager - Acme Corp - Tel Aviv | Indeed"
      Greenhouse / Lever   "Senior PM | Acme Corp"
      Generic ATS          "Product Manager – B2B Platform (REF-4820)"
    """
    title = raw.strip()

    # 1. Strip leading notification count: "(3) Title…" → "Title…"
    title = re.sub(r"^\(\d+\)\s*", "", title)

    # 2. Drop everything at and after the first " | " — site name suffix.
    #    e.g. "Product Analyst at Recruitx | LinkedIn" → "Product Analyst at Recruitx"
    if " | " in title:
        title = title.split(" | ")[0].strip()

    # 3. LinkedIn pattern: "<Company> hiring <Job Title> in <Location>"
    #    Extract the job title between "hiring" and "in <City>".
    hiring_match = re.match(
        r"^.+?\bhiring\s+(.+?)(?:\s+in\s+.+)?$",
        title,
        re.IGNORECASE,
    )
    if hiring_match:
        title = hiring_match.group(1).strip()

    # 4. "Job Title at Company" → keep only "Job Title"
    #    Only strip when "at" precedes a capitalised company-like token so we
    #    don't clip titles that legitimately contain the word "at".
    at_match = re.match(
        r"^(.+?)\s+at\s+[A-Z][^\s,]+",
        title,
    )
    if at_match:
        title = at_match.group(1).strip()

    # 5. Drop company/location suffix segments separated by " – " or " - ".
    #    Indeed format: "Title - Company - Location" (2+ separators) → keep first.
    #    Single separator like "PM – Growth" is kept as-is (likely part of title).
    sep_re = re.compile(r"\s+[-–]\s+")
    parts = sep_re.split(title)
    if len(parts) >= 3:
        # 2+ separators → definitely "Title - Company - Location" style; take first part.
        title = parts[0].strip()
    elif len(parts) == 2:
        # 1 separator → strip only when the tail is a bare company/site name:
        # all-word characters, starts with a capital letter, no digits.
        tail = parts[1].strip()
        if re.match(r"^[A-Z][A-Za-z\s&.]{2,}$", tail) and not re.search(r"\d", tail):
            title = parts[0].strip()

    # 6. Strip internal job-reference codes and their surrounding brackets.
    #    e.g. "JB-5141", "(REF-4820)", "#12345"
    title = re.sub(
        r"\s*[\(\[]?\b(JB|REF|ID|JOB|NO|RQ|RC|IND)[-#]?\s*\d{3,}\b[\)\]]?",
        "", title, flags=re.IGNORECASE,
    )
    title = re.sub(r"\s*[\(\[]\s*#?\d{4,}\s*[\)\]]", "", title)
    # Drop empty brackets left after code removal: "()" or "( )"
    title = re.sub(r"\s*[\(\[]\s*[\)\]]", "", title)

    # 7. Collapse any double spaces introduced by removals above.
    title = re.sub(r"\s{2,}", " ", title).strip()

    return title or raw.strip()  # never return empty string

# Phrases that indicate an error/empty page rather than a real job posting.
# Matched case-insensitively against the full scraped text.
_ERROR_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"an error occurred",
        r"an error has occurred",
        r"something went wrong",
        r"no open positions",
        r"no positions available",
        r"this (job|position|listing|role) (is|has been) (no longer |)(available|open|active|filled|closed|removed|expired)",
        r"page not found",
        r"404 not found",
        r"access denied",
        r"you do not have permission",
        r"login (required|to view)",
        r"please (log in|sign in) to (view|see|access)",
    ]
]


@dataclass
class ScrapedJob:
    title: str
    company: str
    raw_text: str


def scrape_job_post(url: str) -> ScrapedJob:
    """
    Fetch a job posting URL and return structured scraped content.
    Raises requests.HTTPError / requests.Timeout on network failure
    so callers can catch and surface a meaningful 502.
    """
    # ── ATS structured APIs ───────────────────────────────────────────────────
    # Greenhouse and Lever expose public JSON APIs mirroring their hosted
    # pages — prefer these over generic HTML scraping when the URL matches.
    # Any failure (unrecognized path, network error, thin content) falls
    # through to the generic scraper below.
    for api_fn in (try_greenhouse_api, try_lever_api, try_workday_api):
        api_result = api_fn(url)
        if api_result is not None:
            return ScrapedJob(
                title=api_result["title"],
                company=api_result["company"],
                raw_text=api_result["raw_text"],
            )

    response = requests.get(url, headers={"User-Agent": _UA}, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # ── Title ─────────────────────────────────────────────────────────────────
    # og:title is usually the cleanest signal on most ATS platforms.
    # LinkedIn page titles include company/location/site-name noise that
    # _clean_job_title() strips down to just the job title.
    og_title_tag = soup.find("meta", property="og:title")
    og_title   = og_title_tag.get("content", "").strip() if og_title_tag else ""
    page_title = soup.title.get_text(strip=True) if soup.title else ""
    raw_title  = og_title or page_title or "Unknown Title"
    title      = _clean_job_title(raw_title)

    # ── Company ───────────────────────────────────────────────────────────────
    og_site_tag = soup.find("meta", property="og:site_name")
    company = og_site_tag.get("content", "").strip() if og_site_tag else ""
    if not company:
        # fall back to the first segment of the hostname ("greenhouse" → "Greenhouse")
        host = urlparse(url).hostname or ""
        company = re.sub(r"^www\.", "", host).split(".")[0].capitalize()

    # ── Strip noise elements everywhere before content extraction ────────────
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.extract()
    # Remove elements that commonly hold sidebar/recommended-jobs/footer noise.
    # Covers both class= and id= attributes so variant naming is caught.
    _NOISE_PATTERN = re.compile(
        r"sidebar|side[-_]bar|related[-_]?jobs?|recommended|similar[-_]?jobs?|"
        r"more[-_]?jobs?|widget|banner|promo|ad[-_]|"
        r"footer|cookie|modal|overlay|popup|newsletter|"
        r"social[-_]?share|breadcrumb|pagination|tag[-_]?cloud",
        re.I,
    )
    for tag in soup(attrs={"class": _NOISE_PATTERN}):
        tag.decompose()
    for tag in soup(attrs={"id": _NOISE_PATTERN}):
        tag.decompose()

    # ── Focus on the primary content area, fall back to full body ─────────────
    # Preference order: <main>, <article>, role="main", common job-content
    # container IDs/classes, then the full body.
    content_node = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.find(id=re.compile(r"job[_-]?(description|content|detail|post|body)", re.I))
        or soup.find(attrs={"class": re.compile(
            r"job[_-]?(description|content|detail|post|body)|"
            r"posting[_-]?(content|body|detail)|"
            r"position[_-]?(description|detail)|"
            r"jd[_-]?content",
            re.I,
        )})
        or soup.body
    )

    text = visible_text(content_node or soup, separator=" ")
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    raw_text = "\n".join(chunk for chunk in chunks if chunk)

    # Truncate at the first "other jobs" / footer noise anchor so sidebar
    # content from aggregator sites never leaks into the JD text.
    _CUTOFF_ANCHORS = (
        "similar jobs", "people also viewed", "more jobs like this",
        "recommended jobs", "other openings", "jobs you may like",
        "© ", "all rights reserved", "privacy policy", "cookie policy",
    )
    raw_lower = raw_text.lower()
    for anchor in _CUTOFF_ANCHORS:
        idx = raw_lower.find(anchor)
        if idx != -1:
            raw_text = raw_text[:idx].rstrip()
            raw_lower = raw_lower[:idx]
            break

    # Check for error/empty page patterns before the length guard
    for pattern in _ERROR_PATTERNS:
        m = pattern.search(raw_text)
        if m:
            raise ValueError(
                f"Page appears to be an error or empty-state page "
                f"(matched: '{m.group(0)}'). "
                "The job posting may be expired, removed, or behind a login wall."
            )

    if len(raw_text) < 50:
        raise ValueError(
            f"Scraped content is too short ({len(raw_text)} chars) — "
            "the page may be JavaScript-rendered, gated behind auth, or blocked. "
            "Raw preview: " + raw_text[:200]
        )

    return ScrapedJob(title=title, company=company, raw_text=raw_text)
