"""
Which title terms the job-board scrapers search for in one cycle.

Why this exists
----------------
The Israeli boards (Drushim, AllJobs, Gotfriends, Dialog, Nisha) and the
Google Dork scraper searched only config.TARGET_SEARCH_QUERIES — the
founder's own Product / Customer Success / Operations roles. An insurance
agent, a pension advisor, a nurse or a teacher who picked their role in
onboarding got almost nothing from these sources: the board was never asked
for their profession, and the few cards that came back were thrown away by
the global title gate before the detail page was even fetched.

services/user_title_terms.py already turns each user's roles into title
search terms (synonyms + Hebrew forms, one cached LLM call). This module turns
those per-user lists into the short list one scrape cycle may send.

How cost is bounded
--------------------
Every term is one search request per board (plus up to _MAX_PAGES result
pages), so the term count is the cost lever:

* union_terms() merges all users' terms with no duplicates: case, Hebrew
  nikud and the gendered "/ת" suffix are normalised away, and a term whose
  search is already covered by a shorter multi-word term is dropped ("Senior
  Product Manager" is covered by "Product Manager").
* select_for_cycle() caps the list (config.BOARD_TERMS_PER_CYCLE /
  DORK_TERMS_PER_CYCLE) and rotates through the rest over later cycles, so a
  long union is covered over a day instead of firing hundreds of requests at
  once. For the Israeli boards a share of the slots goes to Hebrew terms
  first — that is how those boards' postings are titled.
* No LLM call happens here: callers pass terms read from the cache.

This only decides what is SEARCHED. Who receives a job is decided per user by
relevancy.build_title_matcher(), and scoring is untouched (Core Scoring
Principles in CLAUDE.md).
"""
from __future__ import annotations

import logging
import math
import re
from typing import Iterable

from backend.scrapers.relevancy import _normalise_for_user

logger = logging.getLogger(__name__)

_HEBREW = re.compile(r"[֐-׿]")


def is_hebrew(term: str) -> bool:
    return bool(_HEBREW.search(term or ""))


def _key(term: str) -> str:
    return re.sub(r"\s+", " ", _normalise_for_user(term or "")).strip()


def _covers(short: str, long: str) -> bool:
    """
    True when a board search for *short* already returns *long*'s postings.

    Only a multi-word term may cover others: a single word like "Manager"
    would technically contain "Product Manager", but searching it brings back
    five pages of unrelated managers and loses the specific role.
    """
    if short == long or " " not in short or short not in long:
        return False
    return re.search(rf"(?<!\w){re.escape(short)}(?!\w)", long) is not None


def union_terms(per_user: dict[str, Iterable[str]]) -> list[str]:
    """
    Merge every user's terms into one de-duplicated list.

    Interleaved round-robin across users (each user's first term, then each
    user's second, ...), so that under a cap every user gets their most
    explicit titles searched before anyone's long tail. Users are visited in
    sorted id order to keep the result deterministic.
    """
    lists = [[str(t).strip() for t in per_user[uid] if str(t).strip()] for uid in sorted(per_user)]
    ordered: list[str] = []
    seen: set[str] = set()
    for i in range(max((len(l) for l in lists), default=0)):
        for terms in lists:
            if i < len(terms):
                k = _key(terms[i])
                if k and k not in seen:
                    seen.add(k)
                    ordered.append(terms[i])

    keys = [_key(t) for t in ordered]
    coverers = [k for k in keys if " " in k]
    return [t for t, k in zip(ordered, keys) if not any(_covers(c, k) for c in coverers)]


def _window(items: list[str], n: int, cycle: int) -> list[str]:
    if n <= 0 or not items:
        return []
    if n >= len(items):
        return list(items)
    start = (cycle * n) % len(items)
    return [items[(start + i) % len(items)] for i in range(n)]


def select_for_cycle(
    terms: list[str], cap: int, cycle: int, *, hebrew_share: float = 0.0,
) -> list[str]:
    """
    At most *cap* terms for cycle number *cycle*, rotating through the rest.

    hebrew_share reserves that fraction of the slots for Hebrew terms (used
    for the Israeli boards); unused Hebrew slots go to English terms and vice
    versa, so a list that is all one language still fills the cap.
    """
    if cap <= 0:
        return []
    if len(terms) <= cap:
        return list(terms)
    if hebrew_share <= 0:
        return _window(terms, cap, cycle)

    he = [t for t in terms if is_hebrew(t)]
    en = [t for t in terms if not is_hebrew(t)]
    he_slots = min(len(he), math.ceil(cap * hebrew_share))
    en_slots = min(len(en), cap - he_slots)
    he_slots = min(len(he), cap - en_slots)
    return _window(he, he_slots, cycle) + _window(en, en_slots, cycle)


# ── Rotation cursor ──────────────────────────────────────────────────────────
# Persisted in kv_store, not in memory: the Render free instance restarts on
# every wake-up, and an in-memory cursor would reset to 0 each time and
# search the same first window forever. One tiny row per key.

def next_cycle(key: str) -> int:
    """Return this key's cycle number and advance it. 0 on any storage error."""
    from backend.repositories import kv_repository

    kv_key = f"search_terms_cycle:{key}"
    try:
        entry = kv_repository.get(kv_key)
        cycle = int(entry.value) if entry and entry.value.isdigit() else 0
        kv_repository.upsert(kv_key, str(cycle + 1))
        return cycle
    except Exception as exc:
        logger.warning("[search_terms] rotation cursor %s unavailable, using 0: %s", kv_key, exc)
        return 0
