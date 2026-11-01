"""Regenerate docs/error-catalog.md from the locales and backend/core/errors.py.

Run from the repo root: python backend/scripts/gen_error_catalog.py
"""
import re, sys
sys.path.insert(0,'.')
from backend.core.errors import CODES
def parse(lang):
    s=open(f'frontend/src/locales/{lang}.ts',encoding='utf-8').read()
    out={}
    Q = r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")"""
    for m in re.finditer(r"^\s{6}(\w+):\s*\{ title: "+Q+", why: "+Q+", action: "+Q+r" \}", s, re.M):
        g=m.groups()
        out[g[0]]=tuple((g[i] if g[i] is not None else g[i+1]) for i in (1,3,5))
    return out
he, en = parse('he'), parse('en')
WHEN = {
 'auth_required':'פעולה בלי התחברות (אין טוקן)','session_expired':'טוקן פג או לא תקין',
 'forbidden':'ניסיון לגשת לנתונים של משתמש אחר','admin_only':'מסך ניהול','dev_only':'כלי פיתוח בפרודקשן',
 'auth_not_configured':'חסר SUPABASE_URL בשרת','rate_limited':'יותר מדי בקשות בדקה (כל נתיבי ה-AI)',
 'daily_cv_limit':'מכסת יצירת קו״ח יומית','daily_chat_limit':'מכסת הודעות יומית לאריאל','daily_analysis_limit':'מכסת ניתוחי AI יומית',
 'linkedin_quota':'מכסת RapidAPI החודשית נגמרה','job_not_found':'משרה נמחקה / של משתמש אחר',
 'application_not_found':'הגשה לא קיימת','session_not_found':'שיחת ראיון/היסטוריה פגה',
 'item_not_found':'כל 404 אחר','task_expired':'משימת רקע (ניתוח קישור, העלאת קו״ח) פגה',
 'invalid_input':'שדה חסר או בפורמט שגוי (כל 422 אחר)','empty_message':'שליחת הודעה ריקה',
 'invalid_linkedin_url':'קישור פרופיל לינקדאין שגוי','file_too_large':'קובץ מעל 10MB',
 'unsupported_file':'סוג קובץ שלא נתמך','legacy_doc':'קובץ ‎.doc ישן','file_mismatch':'תוכן הקובץ לא תואם לסיומת',
 'conflict':'פריט במצב שלא מאפשר פעולה (409)','posting_closed':'הקישור מחזיר 404/410',
 'linkedin_login_wall':'לינקדאין דורש התחברות','linkedin_blocked':'לינקדאין חסם כבוט',
 'linkedin_job_not_found':'RapidAPI לא מצא את המשרה וגם העמוד הציבורי לא נקרא',
 'linkedin_unavailable':'מפתח RapidAPI חסר/שגוי','scrape_failed':'כשל בקריאת עמוד המשרה',
 'scrape_empty':'העמוד בלי טקסט משרה','job_no_description':'פעולה שדורשת JD מלא כשיש רק כותרת',
 'job_no_url':'משרה בלי קישור','analysis_failed':'שלב AI בניתוח קישור נכשל (התאמה/מבנה/ציון)',
 'ai_unavailable':'ספק ה-AI לא זמין / מפתח חסר','ai_failed':'פיצ׳ר AI נכשל באמצע (עם שם הפיצ׳ר)',
 'ai_bad_output':'ה-AI החזיר JSON שבור','pdf_unavailable':'רכיב ה-PDF חסר בשרת','pdf_failed':'בניית PDF נכשלה',
 'service_unavailable':'כל 503 אחר','server_error':'שגיאה לא צפויה (500)',
 'network':'הדפדפן לא הגיע לשרת','timeout':'הבקשה לא הסתיימה בזמן','stream_interrupted':'החיבור נותק באמצע תשובת צ׳אט',
 'unknown':'שגיאה בלי קוד מוכר',
}
missing=[c for c in list(CODES)+['network','timeout','stream_interrupted','unknown'] if c not in he or c not in en or c not in WHEN]
assert not missing, missing
def esc(t): return t.replace('|','\\|').replace("\\'","'")
lines=['# טבלת השגיאות — מה המשתמש רואה','',
'> נוצר אוטומטית מ-`frontend/src/locales/{he,en}.ts` ו-`backend/core/errors.py`. אל תערכו ידנית — עדכנו את הטקסטים בקובצי השפה והריצו `python backend/scripts/gen_error_catalog.py`.','',
'## איך זה עובד','',
'1. כל תשובת שגיאה מהשרת כוללת `code` (ולפעמים `params`, למשל `limit`). שגיאה בלי קוד מפורש מקבלת קוד לפי סטטוס ה-HTTP.',
'2. הדפדפן ממפה את הקוד לשלושה חלקים בשפת המשתמש: **מה קרה**, **למה**, **מה לעשות**. הטקסט הטכני של השרת נשמר רק בקונסול ובלוגים.',
'3. הוספת שפה = הוספת אותו בלוק `errors` לקובץ השפה החדש. TypeScript לא יקמפל אם קוד חסר, ובדיקת backend נכשלת אם הקטלוגים לא תואמים.','',
f'**{len(he)} קודים** ({len(CODES)} מהשרת + 4 מהדפדפן).','',
'| קוד | HTTP | מתי זה קורה | מה מוצג בעברית (מה קרה · למה · מה לעשות) | English |','|---|---|---|---|---|']
for c in list(CODES)+['network','timeout','stream_interrupted','unknown']:
    st = CODES.get(c,'—')
    h=he[c]; e=en[c]
    lines.append(f"| `{c}` | {st} | {WHEN[c]} | **{esc(h[0])}** · {esc(h[1])} · {esc(h[2])} | **{esc(e[0])}** · {esc(e[1])} · {esc(e[2])} |")
lines+=['','`{feature}` ב-`ai_failed` מוחלף בשם הפיצ׳ר (למשל "התאמת קורות החיים"). `{limit}` ו-`{max_mb}` מוחלפים במספרים מהשרת.','']
open('docs/error-catalog.md','w',encoding='utf-8').write('\n'.join(lines))
print(len(he))
