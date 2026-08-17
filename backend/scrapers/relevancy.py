"""
Pre-scrape relevancy gate.

is_title_relevant(title) — a fast, zero-network title check used by every
scraper before any detail-page fetch or DB write.  If the job title does
not contain at least one target keyword (or a recognised synonym / abbreviation),
the job is silently discarded so no HTTP requests, LLM calls, or DB rows are
wasted on irrelevant postings.

Design
------
• Builds a single compiled regex from TARGET_SEARCH_QUERIES (config.py)
  plus an explicit set of short aliases that require whole-word matching.
• Normalises input with NFD + strip-Mn so that Hebrew nikud and combined
  Unicode diacritics don't cause false negatives.
• Multi-word phrases are matched as substrings (e.g. "Product Manager"
  matches "Senior Product Manager, Israel").
• Short abbreviations (PM, PO, GPM …) use \\b word-boundary anchors so
  they do not match as substrings of unrelated tokens (e.g. "npm", "RPM").
• The compiled regex is lazily initialised and cached at module level.
  Call reset_pattern() to recompile after changing config (tests only).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

# ── Whole-word short aliases (need \b anchors) ────────────────────────────────
# These are NOT in TARGET_SEARCH_QUERIES because they are too short to be
# useful as standalone search terms on job boards, but they do appear
# frequently in job titles scraped from listing pages.
_WHOLE_WORD_ALIASES: list[str] = [
    # Product
    r"\bpm\b",    # Product Manager
    r"\bpo\b",    # Product Owner
    r"\bgpm\b",   # Group Product Manager
    r"\bspm\b",   # Senior Product Manager
    r"\bcpo\b",   # Chief Product Officer
    r"\bvp\s+product\b",  # "VP Product" / "VP  Product"
    # Customer Success / Account Management
    r"\bcsm\b",   # Customer Success Manager
    r"\bam\b",    # Account Manager (context-dependent — only appears in job titles)
    r"\bkam\b",   # Key Account Manager
]

# ── Phrase aliases (substring match, no word boundary needed) ─────────────────
_PHRASE_ALIASES: list[str] = [
    # Product variants
    "product mgr",
    "product mgmt",
    "product management",   # covers "Head of Product Management"
    "head of product",
    "director of product",
    "product lead",
    "product ops",
    "ראש תחום מוצר",        # Hebrew: "Head of Product Domain"
    "ראש מוצר",             # Hebrew: "Head of Product"
    "מנהל/ת מוצר",          # Hebrew: gender-neutral "Product Manager"
    # CS / Account Management variants
    "customer success manager",
    "customer success lead",
    "customer success director",
    "head of customer success",
    "vp customer success",
    "account management",
    "strategic account",
    "enterprise account",
    "מנהל לקוחות",          # Hebrew: "Account Manager" / "Client Manager"
    "מנהלת לקוחות",
    # ── Added 2026-08-16 ──────────────────────────────────────────────────
    # These live here rather than in TARGET_SEARCH_QUERIES deliberately: they
    # are sentence fragments ("head of customer") or slash-forms that no job
    # board tokenises usefully, so as search terms they would spend a request
    # per scraper per cycle to return noise. As title matchers they are exact.
    "head of customer",       # "Head of Customer Experience/Operations/…"
    "מנהל/ת הצלחת לקוחות",     # gender-neutral slash form of the two in config
    # Operations, senior-anchored — see the config.py note on why a bare
    # "operations manager" was measured and rejected.
    "head of operations",
    "director of operations",
    "operations lead",
]

# ── Module-level cached pattern ───────────────────────────────────────────────
_PATTERN: Optional[re.Pattern] = None  # type: ignore[type-arg]


def _normalise(text: str) -> str:
    """Lower-case + strip Unicode combining marks (handles Hebrew nikud, accents)."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _build_pattern() -> re.Pattern:  # type: ignore[type-arg]
    """
    Compile a single regex from:
      1. TARGET_SEARCH_QUERIES (full phrases, sorted longest-first)
      2. _PHRASE_ALIASES       (full phrases, same matching)
      3. _WHOLE_WORD_ALIASES   (short tokens, \b-anchored)
    """
    from backend.config import TARGET_SEARCH_QUERIES

    # Full phrases — escape special regex chars, longest first to avoid
    # early-exit on a shorter overlapping alternative.
    phrases = sorted(
        set(TARGET_SEARCH_QUERIES) | set(_PHRASE_ALIASES),
        key=len,
        reverse=True,
    )
    phrase_patterns = [re.escape(p) for p in phrases]

    all_parts = phrase_patterns + _WHOLE_WORD_ALIASES
    combined  = "|".join(all_parts)
    return re.compile(combined, re.IGNORECASE)


def is_title_relevant(title: str) -> bool:
    """
    Return True iff *title* contains at least one target keyword or synonym.

    This is a fast local check — no network, no DB.  Designed to be called
    in the listing-page loop of every scraper, before any detail-page fetch.

    Parameters
    ----------
    title : str
        Raw job title as scraped from the listing page or API response.

    Returns
    -------
    bool
        True  → keep the job and proceed with detail fetch / DB write.
        False → discard immediately (no further processing).
    """
    global _PATTERN
    if not title:
        return False
    if _PATTERN is None:
        _PATTERN = _build_pattern()
    normalised = _normalise(title)
    return bool(_PATTERN.search(normalised))


def reset_pattern() -> None:
    """Force pattern recompile on next call.  Use in tests only."""
    global _PATTERN
    _PATTERN = None
