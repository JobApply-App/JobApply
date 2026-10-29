"""
Job-title search that finds what a person means, not just the exact string.

The All Jobs search ran one case-insensitive substring match on the whole
query. Searching "מנהל מוצר" found only titles containing exactly that
phrase: not "Product Manager", not "מנהלת מוצר" or "מנהל/ת מוצר", not
"Manager, Product". A user looking for product roles saw a handful of jobs
and concluded there were none.

expand_title_query() turns one query into a few variants, each a list of
words that must all appear in the title (in any order):

  1. The query's own words. Hebrew words are reduced to a stem, so the
     masculine, feminine and slash forms all match ("מנהלת" -> "מנהל").
  2. The other language, from the same bilingual role catalog the onboarding
     picker uses (role_catalog.json, generated from
     frontend/src/lib/roleCatalog.ts): "מנהל מוצר" also searches
     "Product Manager", and the reverse.
  3. A few interchangeable title words (developer <-> engineer).

"Similar" titles such as "Digital Product Manager" or "מנהל מוצר טכנולוגי"
come from rule 1: every query word appears in them. No LLM call, so the
search stays as fast as it was.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_CATALOG_PATH = Path(__file__).with_name("role_catalog.json")
_MAX_VARIANTS = 8

_HEBREW = re.compile(r"[֐-׿]")
# "/ת", "/ית", "/ה" gender suffixes written after a slash.
_GENDER_SLASH = re.compile(r"/(?:ית|ת|ה|ים|ות)(?=\s|$|\))")
_PUNCT = re.compile(r"[(),.\-–—:|/]+")

# Title words that name the same job. Kept short on purpose: each entry
# widens every search that contains the word.
_INTERCHANGEABLE: dict[str, tuple[str, ...]] = {
    "developer": ("engineer",),
    "engineer": ("developer",),
    "מפתח": ("מהנדס",),
    "מהנדס": ("מפתח",),
}


def _he_stem(word: str) -> str:
    """Strip a Hebrew feminine ending so every gender form matches as a substring."""
    if not _HEBREW.search(word) or len(word) < 4:
        return word
    if word.endswith("ית") and len(word) >= 5:
        return word[:-2]
    if word.endswith(("ת", "ה")):
        return word[:-1]
    return word


def _en_singular(word: str) -> str:
    """'analysts' -> 'analyst' (a substring search still finds the plural)."""
    if _HEBREW.search(word) or len(word) <= 3 or word.endswith("ss") or not word.endswith("s"):
        return word
    return word[:-1]


def _words(text: str) -> list[str]:
    t = _GENDER_SLASH.sub("", (text or "").lower())
    t = _PUNCT.sub(" ", t)
    return [_en_singular(_he_stem(w)) for w in t.split() if w]


@lru_cache(maxsize=1)
def _catalog() -> list[tuple[list[str], list[str]]]:
    roles = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))["roles"]
    return [(_words(r["en"]), _words(r["he"])) for r in roles]


def _same_word(q: str, w: str) -> bool:
    """English: the same word (or its plural). Hebrew: same stem (prefix)."""
    if _HEBREW.search(q):
        return w.startswith(q) or q.startswith(w)
    return q == w or q + "s" == w or w + "s" == q


def _names_role(role: list[str], query: list[str]) -> bool:
    """
    The query names this role: every query word is one of the role's words,
    and the query covers the role — all of a one- or two-word role, all but
    one word of a longer one ("מנהל מוצר" names "Product Marketing Manager"
    loosely, "product" alone names nothing).
    """
    if not role or not all(any(_same_word(q, w) for w in role) for q in query):
        return False
    return len(query) >= len(role) - (1 if len(role) >= 3 else 0)


def expand_title_query(query: str) -> list[list[str]]:
    """
    Variants of a title query; a title matches when it contains every word of
    at least one variant. The query itself is always the first variant.
    Returns [] for a blank query.
    """
    base = _words(query)
    if not base:
        return []
    variants: list[list[str]] = [base]

    def add(v: list[str]) -> None:
        if v and v not in variants and len(variants) < _MAX_VARIANTS:
            variants.append(v)

    # The same role in the other language, when the query names a catalog role
    # (or the meaningful part of one: "מנהל מוצר" covers "מנהל/ת מוצר").
    for en, he in _catalog():
        if _names_role(he, base):
            add(en)
        elif _names_role(en, base):
            add(he)

    for i, w in enumerate(base):
        for alt in _INTERCHANGEABLE.get(w, ()):
            add(base[:i] + [alt] + base[i + 1:])

    return variants


# ── Matching one word ────────────────────────────────────────────────────────
# Hebrew words (stems) and words with symbols ("c++", ".net") match as
# substrings: Hebrew titles attach prefixes (ה, ו, ל) and a stem must reach
# every gender form. Plain English words match whole words, plural allowed,
# so "product" never matches "Production".

_PLAIN_EN = re.compile(r"^[a-z0-9]+$")


def is_whole_word(word: str) -> bool:
    return bool(_PLAIN_EN.match(word))


# The word being typed — the query's last word — matches from the start of a
# title word, so results appear while it is typed ("androi" -> "Android",
# "manag" -> "Manager"). With whole words only, the board showed nothing until
# the word was complete and search felt broken. Every other word stays whole,
# so the finished query "product manager" still skips "Production Manager".
# Short words (IT, PM, QA, HR) stay whole even when typed last: as prefixes
# they would match "Italy" or "PMO".
_PREFIX_MIN = 3


def typing_word(query: str) -> str:
    """The query's last word (normalised like the variants), or "" when none."""
    words = _words(query)
    return words[-1] if words else ""


def is_prefix_word(word: str, typed: str) -> bool:
    return bool(typed) and word == typed and len(word) >= _PREFIX_MIN and is_whole_word(word)


def pg_word_regex(word: str, *, prefix: bool = False) -> str:
    """Postgres ARE for an English word (\\m / \\M = word edges): whole, plural allowed, or a prefix."""
    if prefix:
        return rf"\m{word}"
    return rf"\m{word}(s|es)?\M"


def title_matches(title: str, query: str) -> bool:
    """Python mirror of the SQL filter — used by tests and in-memory callers."""
    t = (title or "").lower()
    typed = typing_word(query)

    def has(word: str) -> bool:
        if is_prefix_word(word, typed):
            return re.search(rf"(?<![a-z0-9]){word}", t) is not None
        if is_whole_word(word):
            return re.search(rf"(?<![a-z0-9]){word}(?:s|es)?(?![a-z0-9])", t) is not None
        return word in t

    return any(all(has(w) for w in v) for v in expand_title_query(query))

