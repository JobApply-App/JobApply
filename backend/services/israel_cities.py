"""
Israeli localities with coordinates, and the proximity factor of the Match Score.

The home city a user gives in onboarding and a job's location string both
resolve to an entry here. israel_localities.json beside this file holds every
recognised locality (see scripts/build_israel_localities.py). Regions use the
same English names as onboarding's area question (routes/profile.py REGIONS).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import NamedTuple, Optional


class City(NamedTuple):
    en: str
    he: str
    lat: float
    lon: float
    region: str
    aliases: tuple[str, ...]
    major: bool
    approx: bool    # placed at its subdistrict's middle, for want of real coordinates


CITIES: tuple[City, ...] = tuple(
    City(**{**row, "aliases": tuple(row["aliases"])})
    for row in json.loads(
        (Path(__file__).resolve().parent / "israel_localities.json").read_text(encoding="utf-8")
    )
)

CITY_BY_NAME: dict[str, City] = {c.en: c for c in CITIES}
RADIUS_OPTIONS_KM = {10, 25, 50}

# Up to this many km from home → composite points. Beyond the last, nothing.
PROXIMITY_TIERS: tuple[tuple[float, float], ...] = ((10.0, 3.0), (25.0, 2.0), (50.0, 1.0))


def _normalize(text: str) -> str:
    """One spelling for matching: no apostrophes or hyphens, and one קרית."""
    text = re.sub(r"['’`׳״\"*]", "", text.casefold())
    text = re.sub(r"[-־–—()]", " ", text).replace("קריית", "קרית")
    return re.sub(r"\s+", " ", text).strip()


_EXACT: dict[str, City] = {}
for _city in CITIES:
    for _name in (_city.en, _city.he, *_city.aliases):
        _EXACT.setdefault(_normalize(_name), _city)

# Only major cities are looked for inside longer text ("Tel Aviv District"). A
# village named Or or Tal would otherwise match half of the job locations.
# Longest first, so "Or Yehuda" is tried before "Yehud" could ever be.
_PATTERNS: tuple[tuple[re.Pattern[str], City], ...] = tuple(
    (re.compile(rf"\b{re.escape(name)}\b"), city)
    for name, city in sorted(
        ((_normalize(n), c) for c in CITIES if c.major for n in (c.en, c.he, *c.aliases)),
        key=lambda pair: -len(pair[0]),
    )
)
_ISRAEL = {"israel", "ישראל"}


def _city_in(segment: str) -> Optional[City]:
    if segment in _EXACT:
        return _EXACT[segment]
    for pattern, city in _PATTERNS:
        if pattern.search(segment):
            return city
    return None


def resolve_city(location: str) -> Optional[City]:
    """
    The locality a job's location names, or None when it names none here.

    Reads "City, District, Country" from the left, so "Ramat Gan, Tel Aviv
    District, Israel" is Ramat Gan and "Tel Aviv District, Israel" is Tel Aviv.
    "Central District, Israel" and "Israel" are None: too wide to measure from.
    A last segment that is neither Israel nor a locality means another country
    ("Acre, Brazil").
    """
    parts = [p for p in (_normalize(s) for s in (location or "").split(",")) if p]
    if not parts:
        return None
    if len(parts) > 1 and parts[-1] not in _ISRAEL and _city_in(parts[-1]) is None:
        return None
    for part in parts:
        city = _city_in(part)
        if city is not None:
            return city
    return None


def distance_km(a: City, b: City) -> float:
    """Great-circle distance between two cities."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def proximity_delta(career_goals: dict, job_location: str) -> Optional[float]:
    """
    Composite points for how close a job is to home, or None when there is no
    signal: no home city, or a job that is remote or has no city we can place.

    0.0 means measured and out of range, either beyond the user's radius or
    outside the regions they picked. The job stays in the feed; it just gains
    nothing. Never negative: distance adds to a match and never takes from one.
    """
    home = CITY_BY_NAME.get(career_goals.get("home_city") or "")
    if home is None or "remote" in (job_location or "").casefold() or "מרחוק" in (job_location or ""):
        return None
    job = resolve_city(job_location)
    if job is None:
        return None

    distance = distance_km(home, job)
    if career_goals.get("search_mode") == "regions":
        regions = career_goals.get("preferred_locations") or []
        if regions and job.region not in regions:
            return 0.0
    else:
        radius = career_goals.get("radius_km")
        if radius and distance > radius:
            return 0.0

    for limit, points in PROXIMITY_TIERS:
        if distance <= limit:
            return points
    return 0.0
