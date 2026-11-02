"""
Regenerates the Israeli localities list. Run by hand, and only when the sources change:

    python backend/scripts/build_israel_localities.py official.json IL.txt

official.json  data.gov.il datastore_search of resource 5c78e9fa-c2e2-4771-93ff-7f400a12f7ba:
               every recognised locality, in Hebrew and English, with its subdistrict.
IL.txt         download.geonames.org/export/dump/IL.zip (CC BY 4.0): the coordinates.

Writes backend/services/israel_localities.json (names, coordinates, region) and
frontend/src/lib/israelLocalities.json (names only). A locality GeoNames does
not know gets the middle of its subdistrict's known localities and approx=true.
Its region is that of the nearest major city.
"""

from __future__ import annotations

import collections
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import NamedTuple


class City(NamedTuple):
    en: str
    he: str
    lat: float
    lon: float
    region: str
    aliases: tuple[str, ...] = ()


# The major cities keep hand-checked names and coordinates, and only they are
# searched for inside longer location strings ("Tel Aviv District").
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



def norm(text: str) -> str:
    text = re.sub(r"['’`׳״\"*]", "", text.casefold())
    text = re.sub(r"[-־–—()]", " ", text).replace("קריית", "קרית")
    return re.sub(r"\s+", " ", text).strip()


def title(text: str) -> str:
    return " ".join("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")) for w in text.split())


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111.2, (a[1] - b[1]) * 111.2 * math.cos(lat))


def main(official_path: str, geonames_path: str) -> None:
    records = json.loads(Path(official_path).read_text(encoding="utf-8"))["result"]["records"]
    places: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for line in Path(geonames_path).read_text(encoding="utf-8").splitlines():
        c = line.split("\t")
        if c[6] == "P":
            for name in {c[1], c[2], *c[3].split(",")}:
                if name:
                    places[norm(name)].append((float(c[4]), float(c[5])))

    majors = {norm(n): c for c in CITIES for n in (c.en, c.he, *c.aliases)}
    rows, seen_en, used_majors = [], set(), set()
    pending = []
    for r in records:
        he, en, sub = r["שם_ישוב"].strip(), r["שם_ישוב_לועזי"].strip(), r["שם_נפה"].strip()
        if not he or he == "לא רשום":
            continue
        major = majors.get(norm(he)) or (majors.get(norm(en)) if en else None)
        if major and major.en not in used_majors:
            used_majors.add(major.en)
            aliases = {a for a in (*major.aliases, he, title(en)) if a and norm(a) not in (norm(major.en), norm(major.he))}
            rows.append({"en": major.en, "he": major.he, "lat": major.lat, "lon": major.lon,
                         "region": major.region, "aliases": sorted(aliases), "major": True, "approx": False, "sub": sub})
            seen_en.add(norm(major.en))
            continue
        stripped = norm(re.sub(r"\(.*?\)", "", he))
        found = places.get(norm(he)) or places.get(stripped) or (places.get(norm(en)) if en else None) or []
        pending.append((he, en, sub, found))

    # Unambiguous names set each subdistrict's middle, which settles the rest.
    by_sub: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for row in rows:
        by_sub[row["sub"]].append((row["lat"], row["lon"]))
    for _he, _en, sub, found in pending:
        if len(found) == 1:
            by_sub[sub].append(found[0])
    middle = {k: (statistics.median(p[0] for p in v), statistics.median(p[1] for p in v)) for k, v in by_sub.items()}

    centres = [((c.lat, c.lon), c.region) for c in CITIES]
    for he, en, sub, found in pending:
        centre = middle[sub]
        point = min(found, key=lambda p: km(p, centre)) if found else None
        approx = point is None or km(point, centre) > 150  # a same-named place far away (the Negev subdistrict is long)
        lat, lon = centre if approx else point
        name = title(en) if en else he
        if norm(name) in seen_en:
            name = f"{name} ({he})"
        seen_en.add(norm(name))
        region = min(centres, key=lambda c: km(c[0], (lat, lon)))[1]
        rows.append({"en": name, "he": he, "lat": round(lat, 4), "lon": round(lon, 4), "region": region,
                     "aliases": [], "major": False, "approx": approx, "sub": sub})

    for c in CITIES:   # major places the official list does not name, like Airport City
        if c.en not in used_majors:
            rows.append({"en": c.en, "he": c.he, "lat": c.lat, "lon": c.lon, "region": c.region,
                         "aliases": list(c.aliases), "major": True, "approx": False, "sub": ""})

    rows.sort(key=lambda r: (not r["major"], r["he"]))
    for row in rows:
        del row["sub"]
    root = Path(__file__).resolve().parents[2]
    (root / "backend/services/israel_localities.json").write_text(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    names = [{"en": r["en"], "he": r["he"], **({"alt": r["aliases"]} if r["aliases"] else {})} for r in rows]
    (root / "frontend/src/lib/israelLocalities.json").write_text(
        json.dumps(names, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(rows)} localities, {sum(r['approx'] for r in rows)} approximate, "
          f"{len(CITIES) - len(used_majors)} major cities not in the official list")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
