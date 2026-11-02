"""
Israeli cities with coordinates, and the proximity factor of the Match Score.

The home city a user gives in onboarding and a job's location string both
resolve to an entry here. Coordinates are city centres, good to a couple of
kilometres, which is all a commute estimate needs. Regions use the same English
names as onboarding's area question (routes/profile.py REGIONS).
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple, Optional


class City(NamedTuple):
    en: str
    he: str
    lat: float
    lon: float
    region: str
    aliases: tuple[str, ...] = ()


_TA, _CE, _SH, _SF = "Tel Aviv", "Center", "Sharon", "Shfela"
_JM, _NO, _SO = "Jerusalem", "Haifa & North", "Be'er Sheva & South"

CITIES: tuple[City, ...] = (
    City("Tel Aviv", "תל אביב", 32.0853, 34.7818, _TA, ("tel aviv yafo", "tel aviv jaffa", "telaviv", "jaffa", "יפו")),
    City("Ramat Gan", "רמת גן", 32.0684, 34.8248, _TA),
    City("Givatayim", "גבעתיים", 32.0722, 34.8125, _TA),
    City("Bnei Brak", "בני ברק", 32.0807, 34.8338, _TA, ("bene beraq",)),
    City("Holon", "חולון", 32.0158, 34.7874, _TA),
    City("Bat Yam", "בת ים", 32.0171, 34.7454, _TA),
    City("Petah Tikva", "פתח תקווה", 32.0871, 34.8875, _CE, ("petach tikva", "petah tiqwa", "petach tikwa", "פתח תקוה")),
    City("Rosh HaAyin", "ראש העין", 32.0956, 34.9566, _CE),
    City("Or Yehuda", "אור יהודה", 32.0292, 34.8567, _CE),
    City("Yehud", "יהוד", 32.0335, 34.8905, _CE, ("yehud monosson", "יהוד מונוסון")),
    City("Ganei Tikva", "גני תקווה", 32.0620, 34.8740, _CE, ("גני תקוה",)),
    City("Kiryat Ono", "קרית אונו", 32.0636, 34.8553, _CE),
    City("Savyon", "סביון", 32.0497, 34.8775, _CE),
    City("Shoham", "שוהם", 31.9987, 34.9456, _CE),
    City("Lod", "לוד", 31.9510, 34.8953, _CE),
    City("Ramla", "רמלה", 31.9293, 34.8664, _CE, ("ramle",)),
    City("Airport City", "איירפורט סיטי", 31.9945, 34.8900, _CE),
    City("Be'er Ya'akov", "באר יעקב", 31.9420, 34.8390, _CE, ("beer yaacov",)),
    City("Modi'in", "מודיעין", 31.8981, 35.0104, _CE, ("modin",)),
    City("Ariel", "אריאל", 32.1042, 35.1745, _CE),
    City("Herzliya", "הרצליה", 32.1624, 34.8447, _SH, ("herzeliya", "herzliyya", "herzelia")),
    City("Ra'anana", "רעננה", 32.1848, 34.8713, _SH),
    City("Kfar Saba", "כפר סבא", 32.1750, 34.9070, _SH, ("kefar sava", "kfar sava")),
    City("Hod HaSharon", "הוד השרון", 32.1500, 34.8880, _SH),
    City("Ramat HaSharon", "רמת השרון", 32.1461, 34.8394, _SH),
    City("Netanya", "נתניה", 32.3215, 34.8532, _SH, ("natanya",)),
    City("Even Yehuda", "אבן יהודה", 32.2700, 34.8880, _SH),
    City("Kadima", "קדימה", 32.2780, 34.9110, _SH, ("kadima zoran", "קדימה צורן")),
    City("Tel Mond", "תל מונד", 32.2500, 34.9170, _SH),
    City("Kfar Yona", "כפר יונה", 32.3170, 34.9350, _SH),
    City("Rishon LeZion", "ראשון לציון", 31.9730, 34.7925, _SF, ("rishon le zion", "rishon lezion")),
    City("Rehovot", "רחובות", 31.8928, 34.8113, _SF),
    City("Ness Ziona", "נס ציונה", 31.9293, 34.7987, _SF, ("nes ziona",)),
    City("Yavne", "יבנה", 31.8780, 34.7390, _SF),
    City("Ashdod", "אשדוד", 31.8014, 34.6435, _SF),
    City("Gedera", "גדרה", 31.8130, 34.7770, _SF),
    City("Mazkeret Batya", "מזכרת בתיה", 31.8540, 34.8460, _SF),
    City("Jerusalem", "ירושלים", 31.7683, 35.2137, _JM),
    City("Beit Shemesh", "בית שמש", 31.7470, 34.9881, _JM),
    City("Mevaseret Zion", "מבשרת ציון", 31.8020, 35.1510, _JM),
    City("Ma'ale Adumim", "מעלה אדומים", 31.7770, 35.2980, _JM),
    City("Haifa", "חיפה", 32.7940, 34.9896, _NO),
    City("Tirat Carmel", "טירת כרמל", 32.7600, 34.9710, _NO),
    City("Nesher", "נשר", 32.7700, 35.0420, _NO),
    City("Kiryat Ata", "קרית אתא", 32.8090, 35.1060, _NO),
    City("Kiryat Bialik", "קרית ביאליק", 32.8270, 35.0850, _NO),
    City("Kiryat Motzkin", "קרית מוצקין", 32.8370, 35.0770, _NO),
    City("Kiryat Yam", "קרית ים", 32.8490, 35.0690, _NO),
    City("Yokneam", "יקנעם", 32.6590, 35.1090, _NO, ("yokneam illit", "yoqneam")),
    City("Hadera", "חדרה", 32.4340, 34.9197, _NO),
    City("Pardes Hanna", "פרדס חנה", 32.4710, 34.9710, _NO, ("pardes hanna karkur", "פרדס חנה כרכור")),
    City("Zichron Ya'akov", "זכרון יעקב", 32.5710, 34.9560, _NO, ("zikhron yaakov", "zichron yaacov")),
    City("Caesarea", "קיסריה", 32.5190, 34.9040, _NO),
    City("Umm al-Fahm", "אום אל פחם", 32.5190, 35.1530, _NO),
    City("Afula", "עפולה", 32.6080, 35.2890, _NO),
    City("Nazareth", "נצרת", 32.6996, 35.3035, _NO),
    City("Nof HaGalil", "נוף הגליל", 32.7070, 35.3270, _NO),
    City("Migdal HaEmek", "מגדל העמק", 32.6760, 35.2400, _NO),
    City("Beit She'an", "בית שאן", 32.4970, 35.4970, _NO),
    City("Tiberias", "טבריה", 32.7922, 35.5312, _NO),
    City("Karmiel", "כרמיאל", 32.9190, 35.2950, _NO, ("carmiel",)),
    City("Akko", "עכו", 32.9281, 35.0818, _NO, ("acre",)),
    City("Nahariya", "נהריה", 33.0060, 35.0940, _NO),
    City("Sakhnin", "סכנין", 32.8650, 35.2960, _NO),
    City("Tamra", "טמרה", 32.8530, 35.1980, _NO),
    City("Safed", "צפת", 32.9650, 35.4960, _NO, ("tzfat", "zefat")),
    City("Rosh Pina", "ראש פינה", 32.9690, 35.5420, _NO),
    City("Katzrin", "קצרין", 32.9910, 35.6910, _NO, ("qazrin",)),
    City("Kiryat Shmona", "קרית שמונה", 33.2070, 35.5690, _NO),
    City("Be'er Sheva", "באר שבע", 31.2518, 34.7913, _SO, ("beersheba", "beer sheba")),
    City("Omer", "עומר", 31.2640, 34.8500, _SO),
    City("Rahat", "רהט", 31.3930, 34.7540, _SO),
    City("Ashkelon", "אשקלון", 31.6688, 34.5743, _SO),
    City("Kiryat Gat", "קרית גת", 31.6100, 34.7640, _SO),
    City("Sderot", "שדרות", 31.5250, 34.5960, _SO),
    City("Netivot", "נתיבות", 31.4200, 34.5890, _SO),
    City("Ofakim", "אופקים", 31.3140, 34.6200, _SO),
    City("Dimona", "דימונה", 31.0680, 35.0330, _SO),
    City("Arad", "ערד", 31.2590, 35.2120, _SO),
    City("Eilat", "אילת", 29.5577, 34.9519, _SO),
)

CITY_BY_NAME: dict[str, City] = {c.en: c for c in CITIES}
RADIUS_OPTIONS_KM = {10, 25, 50}

# Up to this many km from home → composite points. Beyond the last, nothing.
PROXIMITY_TIERS: tuple[tuple[float, float], ...] = ((10.0, 3.0), (25.0, 2.0), (50.0, 1.0))


def _normalize(text: str) -> str:
    """One spelling for matching: no apostrophes or hyphens, and one קרית."""
    text = re.sub(r"['’`׳״\"]", "", text.casefold())
    text = re.sub(r"[-־–—]", " ", text).replace("קריית", "קרית")
    return re.sub(r"\s+", " ", text).strip()


# Longest first, so "Or Yehuda" is tried before "Yehud" could ever be.
_PATTERNS: tuple[tuple[re.Pattern[str], City], ...] = tuple(
    (re.compile(rf"\b{re.escape(name)}\b"), city)
    for name, city in sorted(
        ((_normalize(n), c) for c in CITIES for n in (c.en, c.he, *c.aliases)),
        key=lambda pair: -len(pair[0]),
    )
)
_ISRAEL = {"israel", "ישראל"}


def _city_in(segment: str) -> Optional[City]:
    for pattern, city in _PATTERNS:
        if pattern.search(segment):
            return city
    return None


def resolve_city(location: str) -> Optional[City]:
    """
    The city a job's location names, or None when it names none here.

    Reads "City, District, Country" from the left, so "Ramat Gan, Tel Aviv
    District, Israel" is Ramat Gan and "Tel Aviv District, Israel" is Tel Aviv.
    "Central District, Israel" and "Israel" are None: too wide to measure from.
    A last segment that is neither Israel nor a city means another country
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
