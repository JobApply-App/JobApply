"""
Build the ATS test kit: the same fictional candidate in several files, so a
recruiter can upload them to a real ATS (Comeet first) and we can see what it
extracts. Every file uses a different fictional name, so the files can be
told apart in the ATS. No real person's data.

Run from the repo root:  PYTHONPATH=. python docs/research/test-kit/build_kit.py
Optional: CHROMIUM_PATH=/path/to/chrome when Playwright's own browser is absent.
"""
import asyncio, os, subprocess, sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "x")
OUT = Path(__file__).parent / "files"
OUT.mkdir(exist_ok=True)

if os.getenv("CHROMIUM_PATH"):
    from playwright.async_api._generated import BrowserType
    _orig = BrowserType.launch
    async def _launch(self, *a, **k):
        k.setdefault("executable_path", os.environ["CHROMIUM_PATH"])
        return await _orig(self, *a, **k)
    BrowserType.launch = _launch

from backend.services import pdf_builder as pb

def contact(n, handle):
    return {"name": n, "email": f"{handle}.test@example.com", "phone": "+972-50-000-0000",
            "linkedin": "linkedin.com/in/example-test", "location": "Tel Aviv, Israel"}

EN = {
    "header": {"target_title": "Customer Success Manager"},
    "summary": "Customer Success Manager with 4 years in B2B SaaS. Owned onboarding, renewals and churn prevention for a portfolio of 120 accounts.",
    "experience": [
        {"role": "Customer Success Manager", "company": "Northwind SaaS", "location": "Tel Aviv", "dates": "2023 - 2026",
         "bullets": ["Cut churn from 9% to 5% in 12 months by building an at-risk account playbook in Salesforce.",
                     "Led onboarding for 40 new enterprise customers, reaching first value in 21 days on average.",
                     "Ran quarterly business reviews with VP-level stakeholders across 25 accounts."]},
        {"role": "Customer Support Team Lead", "company": "Contoso Ltd", "location": "Herzliya", "dates": "2021 - 2023",
         "bullets": ["Managed a team of 6 support agents handling 1,500 tickets a month in Zendesk.",
                     "Wrote the escalation process to R&D in Jira, halving time to resolution."]},
    ],
    "education": [{"degree": "B.A. Business Administration", "institution": "Reichman University", "dates": "2018 - 2021"}],
    "skills": {"categories": [{"label": "Customer Success", "items": ["Onboarding", "Renewals", "Churn Prevention", "QBRs"]},
                              {"label": "Tools", "items": ["Salesforce", "Zendesk", "Jira", "SQL"]}]},
    "languages": [{"language": "Hebrew", "level": "Native"}, {"language": "English", "level": "Fluent"}],
    "military_service": {"role": "Operations Officer", "unit": "IDF Intelligence Corps", "dates": "2015 - 2018"},
}
HE = {
    "header": {"target_title": "מנהלת הצלחת לקוחות"},
    "summary": "מנהלת הצלחת לקוחות עם 4 שנות ניסיון ב-B2B SaaS. אחראית על Onboarding, חידושים ומניעת נטישה לתיק של 120 לקוחות.",
    "experience": [
        {"role": "מנהלת הצלחת לקוחות", "company": "Northwind SaaS", "location": "תל אביב", "dates": "2023 - 2026",
         "bullets": ["הורדתי את שיעור הנטישה מ-9% ל-5% תוך 12 חודשים באמצעות תוכנית עבודה ללקוחות בסיכון ב-Salesforce.",
                     "הובלתי Onboarding ל-40 לקוחות אנטרפרייז חדשים, עם זמן ממוצע לערך ראשון של 21 יום.",
                     "קיימתי סקירות עסקיות רבעוניות מול בעלי תפקידים ברמת VP ב-25 לקוחות."]},
        {"role": "ראש צוות תמיכה", "company": "Contoso Ltd", "location": "הרצליה", "dates": "2021 - 2023",
         "bullets": ["ניהלתי צוות של 6 נציגים שטיפל ב-1,500 פניות בחודש ב-Zendesk.",
                     "כתבתי את תהליך ההסלמה לפיתוח ב-Jira, וקיצרתי בחצי את זמן הפתרון."]},
    ],
    "education": [{"degree": "תואר ראשון (B.A.) במנהל עסקים", "institution": "אוניברסיטת רייכמן", "dates": "2018 - 2021"}],
    "skills": {"categories": [{"label": "הצלחת לקוחות", "items": ["Onboarding", "חידושים", "מניעת נטישה", "QBR"]},
                              {"label": "כלים", "items": ["Salesforce", "Zendesk", "Jira", "SQL"]}]},
    "languages": [{"language": "Hebrew", "level": "Native"}, {"language": "English", "level": "Fluent"}],
    "military_service": {"role": "קצינת מבצעים", "unit": "חיל המודיעין", "dates": "2015 - 2018"},
}

PDFS = [  # file name, fictional name, email handle, cv, template, locale
    ("1_EN_modern.pdf",   "Dana Testa",  "dana",  EN, "t2_modern",     "en"),
    ("2_EN_tech.pdf",     "Maya Testa",  "maya",  EN, "t5_techmodern", "en"),
    ("3_HE_modern.pdf",   "נועה טסט",    "noa",   HE, "t2_modern",     "he"),
    ("4_HE_classic.pdf",  "שירה טסט",    "shira", HE, "t1_classic",    "he"),
]

async def build_pdfs():
    for fname, name, handle, cv, tpl, loc in PDFS:
        pb._load_contact = lambda uid, n=name, h=handle: contact(n, h)
        pdf = await pb.build_pdf(cv, template_id=tpl, user_id="kit", cv_locale=loc)
        (OUT / fname).write_bytes(pdf)
        print("built", fname)

def build_word_control():
    """The Hebrew CV written as a plain Word document (no JobApply rendering):
    the control that tells us whether a problem is ours or the ATS's."""
    from docx import Document
    from docx.oxml import OxmlElement
    d = Document()
    def para(text, bold=False):
        p = d.add_paragraph()
        p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
        r = p.add_run(text); r.bold = bold
        r._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
    c = contact("ליאת טסט", "liat")
    para(c["name"], True); para(HE["header"]["target_title"])
    para(f'{c["email"]} | {c["phone"]} | {c["location"]}')
    para("תמצית", True); para(HE["summary"])
    para("ניסיון תעסוקתי", True)
    for e in HE["experience"]:
        para(f'{e["role"]} | {e["company"]} | {e["dates"]}', True)
        for b in e["bullets"]: para("• " + b)
    para("השכלה", True)
    for e in HE["education"]: para(f'{e["degree"]}, {e["institution"]}, {e["dates"]}')
    para("כישורים", True)
    for cat in HE["skills"]["categories"]: para(f'{cat["label"]}: {", ".join(cat["items"])}')
    para("שירות צבאי", True)
    m = HE["military_service"]; para(f'{m["role"]}, {m["unit"]}, {m["dates"]}')
    path = OUT / "5_HE_word_control.docx"
    d.save(path); print("built", path.name)
    try:
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(OUT), str(path)],
                       check=True, capture_output=True, timeout=120)
        (OUT / "5_HE_word_control.pdf").rename(OUT / "6_HE_word_control.pdf"); print("built 6_HE_word_control.pdf")
    except Exception as exc:
        print("LibreOffice not available, skipped the PDF export of the control:", exc)

asyncio.run(build_pdfs())
build_word_control()
