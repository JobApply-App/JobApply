"""Parse downloaded example-CV pages (untrusted data) into one JSON line each.
Usage: python3 -I cvparse.py <cvx_dir> <out.jsonl>
"""
import sys, os, re, json, glob
from bs4 import BeautifulSoup

CANON = [
    ("summary", r"^(professional |career |executive |personal )?(summary|profile|objective|about( me)?|resume summary|resume objective|career objective|personal statement)$"),
    ("experience", r"^((work|professional|relevant|employment|career) )?(experience|history|work experience|employment history)$|^work$|^employment$"),
    ("education", r"^education( and training| & training)?$|^academic (background|history)$"),
    ("skills", r"^((key|core|technical|professional|hard|soft|computer|it|relevant|additional) )?(skills|competencies|strengths|skills & competencies|technologies|tech stack|tools)$|^areas of expertise$|^expertise$"),
    ("languages", r"^languages?( skills)?$"),
    ("projects", r"^((key|personal|academic|selected|notable) )?projects?$"),
    ("certifications", r"^(certifications?|certificates?|licenses?( & | and )certifications?|courses?|training( and | & )?(courses|certifications)?|training)$"),
    ("awards", r"^(awards?|honou?rs?|achievements?|key achievements|accomplishments|awards (and|&) (honou?rs|achievements))$"),
    ("volunteering", r"^(volunteer(ing)?( experience| work)?|community (service|involvement)|extracurricular( activities)?)$"),
    ("interests", r"^(interests|hobbies|hobbies (and|&) interests|passions?|activities)$"),
    ("publications", r"^publications?$|^research$"),
    ("references", r"^references?$"),
]
CANON = [(k, re.compile(p, re.I)) for k, p in CANON]


def canon(h):
    h = re.sub(r"\s+", " ", h).strip(" :").lower()
    for k, p in CANON:
        if p.match(h):
            return k
    return "other:" + h[:40]


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def kick(soup):
    d = soup.select_one("div.text-sample")
    if not d:
        return None
    h1 = soup.select_one("h1")
    comp = [clean(x.get_text(" ")) for x in soup.select(".section--sample-detail .sample-company")]
    hired = ""
    el = soup.find(string=re.compile("Hired by"))
    if el and el.parent and el.parent.parent:
        par = el.parent.parent
        hired = clean(par.get_text(" ")).replace("Hired by:", "").strip()
        if not hired:
            im = par.find("img")
            hired = clean(im.get("alt")) if im and im.get("alt") else ""
    hs = d.find_all("h4")
    out = {"site": "kick", "title": clean(h1.get_text(" ")) if h1 else "", "hired_by": hired, "sections": []}
    cb = hs[0].find_next_sibling("div") if hs else None
    out["contact_labels"] = [clean(x.get_text(" ")).split(":")[0].lower() for x in (cb.find_all("div") if cb else [])]
    og = soup.find("meta", property="og:image")
    out["image"] = og.get("content") if og else ""
    for h in hs[1:]:
        name = clean(h.get_text(" "))
        sibs = []
        for sb in h.next_siblings:
            if getattr(sb, "name", None) == "h4":
                break
            if getattr(sb, "name", None):
                sibs.append(sb)
        box = next((x for x in sibs if x.name == "div"), None)
        sec = {"raw": name, "name": canon(name), "entries": [], "text": clean(" ".join(x.get_text(" ") for x in sibs))}
        if box:
            for ent in box.find_all("div", recursive=False):
                kids = ent.find_all("div", recursive=False)
                if not kids:
                    continue
                head = clean(kids[0].get_text(" "))
                bullets = []
                for k in kids[1:]:
                    lis = k.find_all("li")
                    if lis:
                        bullets += [clean(li.get_text(" ")) for li in lis]
                    else:
                        for p in k.find_all("p") or [k]:
                            t = clean(p.get_text(" "))
                            if t:
                                bullets.append(t)
                sec["entries"].append({"head": head, "bullets": [b for b in bullets if b], "list": bool(ent.find("li"))})
        out["sections"].append(sec)
    # the profile/summary in kick sits in the first block sometimes
    return out


def cf(soup):
    m = soup.select_one("main.resume")
    if not m:
        return None
    out = {"site": "cf", "title": clean((soup.select_one("h1") or soup.title).get_text(" ")), "hired_by": "", "sections": []}
    for s in m.select("section.rs-section"):
        h = s.select_one(".rs-title") or s.find(["h2", "h3", "h4"])
        name = clean(h.get_text(" ")) if h else ""
        body = clean(s.get_text(" "))
        sec = {"raw": name, "name": canon(name), "entries": [], "text": body[len(name):].strip()}
        for e in s.select(".rs-entry"):
            bl = [clean(li.get_text(" ")) for li in e.select("ul.rs-bullets li")]
            for u in e.select("ul"):
                u.extract()
            sec["entries"].append({"head": clean(e.get_text(" ")), "bullets": bl, "list": True})
        out["sections"].append(sec)
    return out


def enh(soup):
    pages = soup.select(".resume-renderer-page")
    if not pages:
        return None
    pages = pages[: max(1, len(pages) // 2)] if len(pages) % 2 == 0 else pages
    out = {"site": "enh", "title": clean((soup.select_one("h1") or soup.title).get_text(" ")), "hired_by": "",
           "sections": [], "pages": len(pages)}
    fonts, sizes, colors = {}, {}, {}
    cols = 0
    for p in pages:
        cc = p.select('[class*="columnContainer"]')
        for c in cc:
            n = len([x for x in c.find_all("div", recursive=False)])
            cols = max(cols, n)
        for el in p.find_all(True):
            st = el.get("style") or ""
            t = clean(el.get_text(" ")) if not el.find(True) or "white-space" in st else ""
            n = len(t)
            if not n:
                continue
            m = re.search(r'font-family:\s*"?([^",;]+)', st)
            if m:
                fonts[m.group(1)] = fonts.get(m.group(1), 0) + n
            m = re.search(r"font-size:\s*([\d.]+)px", st)
            if m:
                sizes[m.group(1)] = sizes.get(m.group(1), 0) + n
            m = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{3,6})", st)
            if m:
                colors[m.group(1).upper()] = colors.get(m.group(1).upper(), 0) + n
        cur = None
        for el in p.find_all("div"):
            cls = " ".join(el.get("class") or [])
            if "sectionName" in cls:
                name = clean(el.get_text(" "))
                cur = {"raw": name, "name": canon(name), "entries": [], "text": ""}
                out["sections"].append(cur)
            elif "resume-item-holder" in cls and cur is not None:
                bl = [clean(li.get_text(" ")).lstrip("• ").strip() for li in el.select('ul[class*="Bullets-module_ul"] li')]
                pos = el.select_one(".item-position")
                cur["entries"].append({"head": clean(pos.get_text(" ")) if pos else "", "bullets": [b for b in bl if b], "list": True})
                cur["text"] += " " + clean(el.get_text(" "))
    out["fonts"], out["sizes_px"], out["colors"], out["cols"] = fonts, sizes, colors, cols
    hdr = pages[0].select_one('[class*="resumeHeader"]')
    out["header_classes"] = " ".join(hdr.get("class") or []) if hdr else ""
    return out


def main():
    root, outp = sys.argv[1], sys.argv[2]
    n = ok = 0
    with open(outp, "w") as fo:
        for site, fn in (("kick", kick), ("cf", cf), ("enh", enh)):
            for f in sorted(glob.glob(os.path.join(root, site, "*.html"))):
                n += 1
                try:
                    soup = BeautifulSoup(open(f, errors="ignore").read(), "html.parser")
                    r = fn(soup)
                except Exception as e:  # report loudly, never silently
                    print("PARSE-ERROR", f, repr(e)[:120], file=sys.stderr)
                    continue
                if not r or not r["sections"]:
                    print("EMPTY", f, file=sys.stderr)
                    continue
                r["file"] = os.path.basename(f)
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
                ok += 1
    print("files", n, "parsed", ok)


main()
