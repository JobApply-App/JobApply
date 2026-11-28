"""
One way to tell whether two company names are the same company.

Before this there were five normalizers (docs/research/09-companies-and-costs.md
§1.1). The one in agents/company_culture.py kept only a-z0-9, so every Hebrew
name became an empty key, and none of them treated "Wix" and "Wix.com" or
"Wiz" and "Wiz (a Google Company)" as one company.

Two identities, strongest first:
  1. linkedin_slug(): the /company/<slug> part of LinkedIn's company link.
     It is LinkedIn's own id for the page, so it joins spellings no rule
     could ("Nisha - נישה" and "Nisha Group - קבוצת נישה").
  2. company_key(): a name normalization for everything else. Keeps Hebrew,
     drops legal suffixes, domain endings and parentheses.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional
from urllib.parse import unquote

_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_QUOTES = re.compile(r"[\"'׳״`’]")
_DOMAIN_END = re.compile(r"\.(?:co\.il|com|io|ai|co|net|org)\b")
_NON_WORD = re.compile(r"[^\w]+|_")
# Legal forms that never tell two companies apart.
_LEGAL_ANYWHERE = {"ltd", "inc", "llc", "corp", "limited", "plc", "gmbh", "בעמ"}
# Too short to drop from the middle of a name, safe at the end.
_LEGAL_AT_END = {"co", "sa", "bv", "ag"}

_LINKEDIN_COMPANY = re.compile(r"linkedin\.com/company/([^/?#]+)", re.IGNORECASE)


def company_key(name: Optional[str]) -> Optional[str]:
    """'Vishay Precision Group, Inc. (VPG)' -> 'vishay precision group';
    'monday.com' -> 'monday'; 'Strauss Water Ltd. שטראוס מים' ->
    'strauss water שטראוס מים'. None when nothing is left."""
    if not name:
        return None
    text = unicodedata.normalize("NFKC", str(name)).casefold()
    text = _BRACKETS.sub(" ", text)
    text = _QUOTES.sub("", text)
    text = _DOMAIN_END.sub(" ", text)
    tokens = [t for t in _NON_WORD.sub(" ", text).split() if t not in _LEGAL_ANYWHERE]
    while len(tokens) > 1 and tokens[-1] in _LEGAL_AT_END:
        tokens.pop()
    return " ".join(tokens) or None


def linkedin_slug(url: Optional[str]) -> Optional[str]:
    """'https://il.linkedin.com/company/wix-com?trk=x' -> 'wix-com'."""
    if not url:
        return None
    m = _LINKEDIN_COMPANY.search(url)
    if not m:
        return None
    slug = unquote(m.group(1)).strip().lower()
    return slug or None
