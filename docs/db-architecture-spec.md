# אפיון ארכיטקטורת מסד הנתונים — מ-26 טבלאות ל-19

**מסמך אפיון · JobApply_Venture · Supabase Postgres**
נכתב על בסיס סריקת סכימה חיה + ניתוח קוד ה-Backend, 2026-07-31

---

## 0. תקציר מנהלים

הסכימה הנוכחית עברה ניקוי מוצלח (29 → 26 טבלאות), אבל היא עדיין **לא מוכנה לריבוי משתמשים**. שלוש בעיות שורש:

| # | הבעיה | העדות המספרית |
|---|-------|----------------|
| 1 | **אין עוגן דיירות** — רק 5 מתוך 19 הטבלאות המשתמש-תלויות מקושרות ל-`profiles` ב-FK | **41 שורות יתומות** כבר קיימות ב-6 טבלאות |
| 2 | **אותה ישות מיוצגת פעמיים** — כישורים, שיחות, ומשרות מנוהלים בטבלאות מקבילות בלי קשר ביניהן | 36 כישורים ב-`cv_claims` מול 121 ב-`profile_entities`, **0 קישור** |
| 3 | **מינוח אישי במקום גנרי** — `why_ron` כשם עמודה במוצר רב-משתמשי | 113 שימושים ב-Backend + 16 ב-Frontend, ונחשף כמפתח JSON ב-5 ראוטים |

**היעד:** 19 טבלאות, כל אחת עם ייעוד יחיד, כולן תלויות ב-`profiles.id` כעוגן, ללא כפילות מושגית.

---

## 1. חמישה עקרונות יסוד

עקרונות מחייבים לכל שינוי סכימה עתידי. כל PR שסותר אחד מהם — נדחה.

### עיקרון 1 — `profiles.id` הוא עוגן הדיירות היחיד

כל טבלה שמחזיקה נתון השייך למשתמש **חייבת** עמודה:

```sql
user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE
```

לא `TEXT`. לא `VARCHAR`. לא בלי FK. מחיקת משתמש חייבת לנקות אחריה את כל שרשרת הנתונים אוטומטית.

### עיקרון 2 — לישות אחת בעולם האמיתי יש שורה אחת

"Figma כישור של המשתמש" הוא דבר אחד. אם הוא מופיע גם ב-`cv_claims` וגם ב-`profile_entities` — זו כפילות שחייבת איחוד, לא שתי אמיתות מקבילות.

### עיקרון 3 — פיצ'ר חדש מרחיב טבלה קיימת, אלא אם יש סיבה מבנית

טבלה חדשה מוצדקת **רק** כאשר מתקיים אחד מאלה:
- **קרדינליות שונה** — יחס 1:N אמיתי (למשל: ראיות רבות לכישור אחד)
- **מחזור חיים שונה** — נתון append-only מול נתון שמתעדכן
- **תחום בעלות שונה** — נתון גלובלי מול נתון פרטי-משתמש

אם הנתון הוא 1:1 עם שורה קיימת — הוא **עמודה**, לא טבלה.

### עיקרון 4 — הפרדה בין גלובלי לפרטי, לא בין "גלוי" ל"מוסתר"

אין להקים טבלה כפולה רק כדי להסתיר מידע בהקשר מסוים. ההסתרה נעשית ב-`SELECT` וב-RLS, לא בשכפול טבלאות. טבלה אחת + `VIEW`/פרויקציה לכל הקשר.

### עיקרון 5 — מינוח נייטרלי ורב-משתמשי

אין שמות עמודות/סקריפטים/קבועים שמתייחסים לאדם ספציפי. המערכת משרתת כל משתמש שנרשם אליה.

---

## 2. הממצאים — מה שבור היום

### 2.1 פער הדיירות (החמור ביותר)

רק 5 טבלאות מקושרות ל-`profiles.id` ב-FK תקין: `user_preferences`, `profile_answers`, `cv_documents`, `user_job_matches`, ו-`cv_claims` (בעקיפין).

**14 טבלאות מחזיקות `user_id` כמחרוזת חופשית ללא FK.** התוצאה כבר במסד:

| טבלה | שורות יתומות | מתוך סה"כ |
|------|--------------|-----------|
| `chat_sessions` | **10** | 14 |
| `evidence_records` | **13** | 256 |
| `shadow_match_scores` | **13** | 24 |
| `profile_entities` | 2 | 163 |
| `confidence_audit_log` | 2 | 208 |
| `ariel_sessions` | 1 | 34 |
| **סה"כ** | **41** | — |

זה נתון של משתמשים שכבר לא קיימים — עם 100 משתמשים אמיתיים זה יהפוך לאלפי שורות זבל שאף אחד לא יכול למחוק בבטחה.

### 2.2 כפילות מושגית: כישורים בשני מקומות

| מקור | תוכן | דוגמה |
|------|------|--------|
| `cv_claims` (36 כישורים) | טענה גולמית מהקו"ח | `{"name": "Figma"}` |
| `profile_entities` (121 כישורים) | ישות מנוקדת עם אמינות | `Figma · score=45.5 · partial` |

**אין ביניהן שום קישור.** אותו כישור חי פעמיים, ואם הוא מתעדכן בצד אחד — הצד השני לא יודע. זו בדיוק התחושה שהעלית לגבי ה-Confidence Matrix: הוא לא "ליד" הפרופיל, הוא **אמור להיות** הפרופיל.

### 2.3 כפילות מושגית: שלוש טבלאות שיחה

| טבלה | שורות | מה היא מייצגת |
|------|-------|----------------|
| `chat_sessions` | 14 | שיחה חופשית עם Ariel |
| `ariel_sessions` | 34 | מפגש חקירה יזום |
| `profile_interviews` | 17 | ראיון onboarding מובנה |

**0 `session_id` משותפים בין כל זוג.** שלושה ממגורות מקבילות לאותו מושג — "שיחה בין המשתמש למערכת" — כל אחת עם סכימה משלה. פיצ'ר שיחה רביעי יוליד טבלה רביעית.

### 2.4 `all_jobs` מול `job_postings` — לא כפילות, אבל **חסר קישור**

בדקתי בפועל:

```
all_jobs      : 753 שורות, canonical_job_key = "4442371810"      ← מזהה LinkedIn מספרי
job_postings  :   4 שורות, canonical_job_key = "9ca83e8de4e16f8a" ← hash של כותרת+חברה+מיקום
חפיפה         : 0
```

הן **לא** מחזיקות אותו מידע, ולכן אין למזג אותן:

- `all_jobs` = **צינור קליטה גולמי**. מכיל גם רעש שאינו משרה כלל (בדגימה: `"David Dayag (Deddy)"`, `"So schreibst du ein Exposé"` — פוסטים של LinkedIn, לא משרות).
- `job_postings` = **קטלוג מאושר** של משרות שעברו סינון והפכו רלוונטיות למישהו.

**הבעיה האמיתית:** שני מפתחות קנוניים שונים לאותו עולם תוכן, בלי קשר. אותה משרת LinkedIn תיקלט ב-`all_jobs` ותקודם ל-`job_postings` כשתי רשומות זרות. **הפתרון הוא קישור, לא מיזוג.**

### 2.5 טבלאות שהן למעשה עמודות

ארבע טבלאות מחזיקות יחס **1:1 מדויק** עם `user_job_matches` — כלומר הן עמודות שהוגלו לטבלה:

| טבלה | היחס | היעד |
|------|------|------|
| `match_triggers` | 1:1 עם (משתמש, משרה) שחצתה סף | עמודות ב-`user_job_matches` |
| `job_feedback` | 1:1 עם (משתמש, משרה) שקיבלה משוב | עמודות ב-`user_job_matches` |
| `recruiter_reply_drafts` | 1:1 עם (משתמש, משרה) שהגיעה אליה פנייה | עמודות ב-`user_job_matches` |
| `ariel_probe_log` | אירוע בתוך שיחה | שורה ב-`conversation_events` |

`user_job_matches` כבר מחזיקה `outreach_text` — כלומר התקדים לכיוון הזה כבר קיים בסכימה.

### 2.6 `profile_answers` — הטבלה הגנרית שאני בניתי

אני צריך להיות ישר כאן: `profile_answers` היא בדיוק סוג הטבלה שהתרעת מפניה. בניתי אותה ב-Phase 3 כגשר פרגמטי — כדי לא לאבד אף מפתח מה-JSON הישן של `master_profiles` בלי למפות ידנית עשרות שדות אד-הוק.

היא מילאה את תפקידה, אבל **היא לא היעד**. המפתחות שחיים בה כרגע (`career_goals`, `metrics_doc`, `baseline_snapshot`, `enriched_entities`, `user_persona`, `cv_data`) הם ישויות אמיתיות שמגיע להן מבנה טיפוסי. האפיון כולל מסלול "בוגר" עבורם.

---

## 3. מודל היעד — 19 טבלאות

```
                          ┌─────────────┐
                          │  profiles   │  ← עוגן דיירות יחיד (FK ל-auth.users)
                          │   (id UUID) │
                          └──────┬──────┘
        ┌────────────────┬───────┼────────┬──────────────┬─────────────┐
        │                │       │        │              │             │
┌───────▼────────┐ ┌─────▼─────┐ │ ┌──────▼──────┐ ┌─────▼──────┐ ┌───▼────────┐
│user_preferences│ │cv_documents│ │ │conversations│ │applications│ │shadow_match│
│     (1:1)      │ │            │ │ │  kind=chat/ │ │    CRM     │ │  _scores   │
└────────────────┘ └─────┬──────┘ │ │probe/interv.│ └─────┬──────┘ └────────────┘
                         │        │ └──────┬──────┘       │
                    ┌────▼────────▼──┐     │              │
                    │profile_entities│     │        ┌─────▼─────────────┐
                    │  ← cv_claims   │◄────┤        │ user_job_matches  │
                    │  כישור/ניסיון/  │     │        │ ← match_triggers  │
                    │  השכלה/תחום    │     │        │ ← job_feedback    │
                    └────┬───────┬───┘     │        │ ← reply_drafts    │
                         │       │         │        └─────────┬─────────┘
              ┌──────────▼──┐ ┌──▼─────────▼──────┐           │
              │  evidence   │ │conversation_events│    ┌──────▼──────┐
              │  _records   │ │ ← ariel_probe_log │    │job_postings │ קטלוג גלובלי
              │(append-only)│ └───────────────────┘    └──────┬──────┘
              └──────┬──────┘                                 │ source_all_job_id
                     │                                 ┌──────▼──────┐
           ┌─────────▼──────────┐                      │  all_jobs   │ קליטה גולמית
           │confidence_audit_log│                      └─────────────┘
           └────────────────────┘
                                       גלובלי (ללא בעלות משתמש):
                                       company_intel · kv_store · alembic ×2
```

### מיפוי מלא: 26 → 19

| # | טבלה נוכחית | פעולה | יעד |
|---|-------------|--------|-----|
| 1 | `profiles` | ✅ נשארת | עוגן — מקבלת FK מכולם |
| 2 | `user_preferences` | ✅ נשארת | תקינה כבר היום |
| 3 | `profile_answers` | ⚠️ מצטמצמת | מפתחות מוכרים → מבנה טיפוסי |
| 4 | `cv_documents` | ✅ נשארת | תיעוד מקור |
| 5 | `cv_claims` | 🔀 **ממוזגת** | → `profile_entities` |
| 6 | `profile_entities` | 🔧 מורחבת | קולטת `cv_claims`, FK ל-`profiles` |
| 7 | `evidence_records` | 🔧 מתוקנת | FK ל-`profiles` |
| 8 | `confidence_audit_log` | 🔧 מתוקנת | FK ל-`profiles` |
| 9 | `all_jobs` | 🔧 מתוקנת | מפתח קנוני מאוחד |
| 10 | `job_postings` | 🔧 מורחבת | + `source_all_job_id` |
| 11 | `user_job_matches` | 🔧 מורחבת | קולטת 3 טבלאות + `why_ron`→`fit_brief` |
| 12 | `match_triggers` | 🔀 **ממוזגת** | → `user_job_matches` |
| 13 | `job_feedback` | 🔀 **ממוזגת** | → `user_job_matches` |
| 14 | `recruiter_reply_drafts` | 🔀 **ממוזגת** | → `user_job_matches` |
| 15 | `applications` | 🔧 מתוקנת | FK ל-`profiles` + ל-`user_job_matches` |
| 16 | `shadow_match_scores` | 🔧 מתוקנת | FK ל-`profiles` (נשארת — כלי מדידה) |
| 17 | `chat_sessions` | 🔀 **ממוזגת** | → `conversations` |
| 18 | `ariel_sessions` | 🔀 **ממוזגת** | → `conversations` |
| 19 | `profile_interviews` | 🔀 **ממוזגת** | → `conversations` |
| — | *(חדשה)* | ➕ | `conversations` |
| 20 | `conversation_events` | 🔧 מורחבת | קולטת `ariel_probe_log` |
| 21 | `ariel_probe_log` | 🔀 **ממוזגת** | → `conversation_events` |
| 22 | `ariel_gap_queue` | 🔧 מתוקנת | FK תקין (ראה §4.6) |
| 23 | `company_intel` | ✅ נשארת | גלובלית, לא משתמש-תלויה |
| 24 | `kv_store` | ✅ נשארת | תשתית |
| 25-26 | `alembic_version` ×2 | ✅ נשארות | תשתית |

**סיכום: 8 טבלאות מתמזגות, 1 נוספת → 19 טבלאות.**

---

## 4. פירוט השינויים

### 4.1 איחוד הפרופיל: `cv_claims` → `profile_entities`

זו התשובה לשאלה "למה ה-Confidence Matrix לא בפרופיל". התשובה: **הוא כן צריך להיות**, וזה האיחוד שעושה את זה.

היום כישור נולד ב-`cv_claims` (טענה מהקו"ח) ומקבל חיים שניים ב-`profile_entities` (ישות מנוקדת) — בלי קשר. אחרי האיחוד יש שורה אחת שמחזיקה גם את הטענה וגם את ציון האמינות שלה.

```sql
-- profile_entities הופכת לטבלת היכולות המרכזית
ALTER TABLE public.profile_entities
  ADD COLUMN content          JSONB,           -- התוכן העשיר שהיה ב-cv_claims
  ADD COLUMN source_document_id UUID REFERENCES public.cv_documents(id) ON DELETE SET NULL,
  ADD COLUMN origin           TEXT NOT NULL DEFAULT 'self_assertion';
                                               -- cv_parse | self_assertion | conversation | inferred

-- הרחבת הטקסונומיה לקלוט את education מ-cv_claims
ALTER TABLE public.profile_entities
  DROP CONSTRAINT IF EXISTS profile_entities_entity_type_check,
  ADD CONSTRAINT profile_entities_entity_type_check
    CHECK (entity_type IN ('skill','trait','domain','experience','education'));
```

**כלל המיזוג:** התאמה לפי `(user_id, normalized_name, entity_type)`. טענה מ-`cv_claims` שכבר קיימת כישות — מעדכנת את `content` ו-`source_document_id` בלבד ולא נוגעת ב-`confidence_score`. טענה שאין לה ישות — נוצרת עם `origin='cv_parse'` וציון התחלתי לפי משקל מקור ה-CV.

**הרווח:** `get_profile()` מחזיר כישורים **עם ציון אמינות מובנה**. ה-Gatekeeper לא צריך שתי שאילתות. עדכון כישור בצ'אט מתגלגל אוטומטית לקו"ח.

### 4.2 `user_job_matches` קולטת שלוש טבלאות

כל השלוש הן 1:1 מדויק עם (משתמש, משרה) — כלומר עמודות שהוגלו.

```sql
ALTER TABLE public.user_job_matches
  -- ← match_triggers (התראת חציית סף)
  ADD COLUMN trigger_state      TEXT,        -- NULL | 'pending' | 'consumed'
  ADD COLUMN trigger_threshold  REAL,
  ADD COLUMN triggered_at       TIMESTAMPTZ,
  ADD COLUMN trigger_consumed_at TIMESTAMPTZ,

  -- ← job_feedback (לולאת הלמידה)
  ADD COLUMN feedback_type      TEXT,        -- 'irrelevant' | 'interested' | 'wrong_seniority' ...
  ADD COLUMN feedback_reason    TEXT,
  ADD COLUMN feedback_at        TIMESTAMPTZ,

  -- ← recruiter_reply_drafts (טיוטת תגובה למגייס)
  ADD COLUMN recruiter_excerpt  TEXT,
  ADD COLUMN reply_draft        TEXT,
  ADD COLUMN reply_draft_status TEXT;

-- אינדקס חלקי — התור נשאר יעיל בלי טבלה נפרדת
CREATE INDEX ix_ujm_pending_triggers ON public.user_job_matches (user_id, triggered_at)
  WHERE trigger_state = 'pending';
CREATE INDEX ix_ujm_feedback ON public.user_job_matches (user_id, feedback_at)
  WHERE feedback_type IS NOT NULL;
```

**למה זה נכון ולא "דחיסה":** אינדקס חלקי (`WHERE trigger_state = 'pending'`) נותן בדיוק את אותה יעילות תור כמו טבלה נפרדת, בלי JOIN ובלי סיכון לחוסר-סנכרון. שאילתת "מה ממתין" נשארת סריקת אינדקס על עשרות שורות, לא על כל הטבלה.

**לגבי `job_feedback` והבקשה שלך ל"טבלה מרכזת שנלמד ממנה":** המשוב **הוא** התכונה הנלמדת של ההתאמה — הוא לא ישות נפרדת. אחרי המיזוג, שאילתת הלמידה הופכת לטריוויאלית:

```sql
-- "מה המשתמש דוחה, ומה המשותף לזה?" — שאילתה אחת, בלי JOIN
SELECT jp.company, jp.title, ujm.feedback_type, ujm.match_score
FROM public.user_job_matches ujm
JOIN public.job_postings jp ON jp.id = ujm.job_posting_id
WHERE ujm.user_id = $1 AND ujm.feedback_type IS NOT NULL;
```

זה בדיוק "לקצר תהליכים במקום להרחיב" — הציון, ההקשר והמשוב יושבים באותה שורה.

### 4.3 `conversations` — איחוד שלוש טבלאות השיחה

```sql
CREATE TABLE public.conversations (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN ('chat','probe','interview')),
  status         TEXT NOT NULL DEFAULT 'active',

  -- שדות משותפים לכל סוגי השיחה
  transcript     JSONB NOT NULL DEFAULT '[]',

  -- kind='probe' (היה ariel_sessions)
  target_job_posting_id UUID REFERENCES public.job_postings(id) ON DELETE SET NULL,
  goal                  TEXT,
  confidence_delta      REAL,

  -- kind='interview' (היה profile_interviews)
  draft_profile  JSONB,
  confidence_map JSONB,
  pending_probes JSONB,
  intent         TEXT,

  started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at       TIMESTAMPTZ
);
CREATE INDEX ix_conversations_user_kind ON public.conversations (user_id, kind, started_at DESC);
```

**התנגדות צפויה — "יש כאן עמודות NULL לפי סוג":** נכון, וזה מקובל. החלופה (שלוש טבלאות) עולה יותר: שלושה repositories, שלוש בדיקות בעלות, ופיצ'ר שיחה רביעי יוליד טבלה רביעית. הגבול שאני מציב: אם `kind` רביעי ידרוש **יותר מ-4 עמודות ייעודיות** — הוא מקבל טבלת לוויין משלו עם FK ל-`conversations.id`, ולא מנפח את הטבלה הראשית.

`conversation_events` נשארת כטבלת התורות/אירועים (יחס 1:N אמיתי — עיקרון 3) וקולטת גם את `ariel_probe_log`:

```sql
ALTER TABLE public.conversation_events
  ADD COLUMN event_kind   TEXT NOT NULL DEFAULT 'star_extraction',  -- + 'probe'
  ADD COLUMN probe_outcome TEXT;
```

### 4.4 `all_jobs` ↔ `job_postings` — קישור, לא מיזוג

**החלטה: לא ממזגים.** הן מייצגות שלבים שונים בצינור (קליטה גולמית מול קטלוג מאושר), ול-`all_jobs` יש 753 שורות שרובן לא יהפכו לעולם למשרה רלוונטית — הזרמתן ל-`job_postings` תזהם את הקטלוג.

**מה כן מתקנים — שני מפתחות קנוניים שונים:**

```sql
-- 1. קישור מפורש: כל job_posting יודע מאיזו שורת קליטה נולד
ALTER TABLE public.job_postings
  ADD COLUMN source_all_job_id UUID REFERENCES public.all_jobs(id) ON DELETE SET NULL;
CREATE INDEX ix_job_postings_source ON public.job_postings (source_all_job_id);

-- 2. מפתח קנוני אחיד — all_jobs מקבלת את אותו hash של title+company+location
ALTER TABLE public.all_jobs
  ADD COLUMN content_key TEXT;   -- canonical_dedup_key(title, company, location)
CREATE INDEX ix_all_jobs_content_key ON public.all_jobs (content_key);
```

`all_jobs.canonical_job_key` נשאר מזהה המקור (LinkedIn ID) — הוא נכון לתפקידו (דה-דופ' מול אותו מקור). `content_key` החדש מאפשר לזהות שמשרה שנקלטה מ-LinkedIn ומשרה שנקלטה מאתר החברה הן **אותה משרה**, ולקדם אותן ל-`job_posting` יחיד.

**התוצאה:** אין כפילות, יש שושלת (lineage) מלאה — מכל כרטיס משרה שהמשתמש רואה אפשר לחזור עד ה-payload הגולמי שנסרק.

### 4.5 סגירת פער הדיירות — 14 טבלאות

זה השינוי החשוב ביותר במסמך. לכל טבלה משתמש-תלויה:

```sql
-- דוגמה מייצגת (חוזר על 14 טבלאות)
-- שלב א: ניקוי יתומים (41 שורות — גיבוי ל-CSV לפני)
DELETE FROM public.profile_entities pe
WHERE NOT EXISTS (SELECT 1 FROM public.profiles p WHERE p.id::text = pe.user_id);

-- שלב ב: המרת טיפוס
ALTER TABLE public.profile_entities
  ALTER COLUMN user_id TYPE UUID USING user_id::uuid;

-- שלב ג: אכיפת הקשר
ALTER TABLE public.profile_entities
  ADD CONSTRAINT fk_profile_entities_user
  FOREIGN KEY (user_id) REFERENCES public.profiles(id) ON DELETE CASCADE;
```

**הטבלאות:** `profile_entities`, `evidence_records`, `confidence_audit_log`, `applications`, `chat_sessions`→`conversations`, `ariel_sessions`→`conversations`, `profile_interviews`→`conversations`, `ariel_gap_queue`, `ariel_probe_log`→`conversation_events`, `conversation_events`, `shadow_match_scores`, `job_feedback`→ממוזגת, `match_triggers`→ממוזגת, `recruiter_reply_drafts`→ממוזגת.

**הרווח המיידי:** מחיקת משתמש הופכת ל-`DELETE FROM profiles WHERE id = $1` — ו-Postgres מנקה את כל השרשרת. היום זו פעולה ידנית מסוכנת ב-14 מקומות. זו גם דרישת GDPR בסיסית לכשיהיו משתמשים אמיתיים.

### 4.6 `ariel_gap_queue` — נשארת, בניגוד למגמת המיזוג

היא **לא** 1:1 עם ישות ולא 1:1 עם משרה — היא צומת של **(יכולת × משרת יעד)**: "הכישור Python שלך ב-45, המשרה הזו דורשת 70". אותו כישור יכול להיות בפער מול חמש משרות במקביל עם דרישות שונות.

לפי עיקרון 3 (קרדינליות שונה) — זו טבלה לגיטימית. היא רק צריכה FK תקין:

```sql
ALTER TABLE public.ariel_gap_queue
  ALTER COLUMN user_id TYPE UUID USING user_id::uuid,
  ADD CONSTRAINT fk_gap_user FOREIGN KEY (user_id)
    REFERENCES public.profiles(id) ON DELETE CASCADE,
  ADD COLUMN job_posting_id UUID REFERENCES public.job_postings(id) ON DELETE CASCADE;
```

### 4.7 `confidence_audit_log` — נשארת, והנה למה

ביקשת לשקול למזג אותה עם `evidence_records`. **אני ממליץ לא**, מהסיבה הבאה:

| | `evidence_records` | `confidence_audit_log` |
|---|---|---|
| מייצג | **קלט** — "מה למדנו על המשתמש" | **פלט** — "איך הציון זז וכמה" |
| מחזור חיים | append-only, עם תפוגה (`hard_expires_at`) | append-only, נצחי |
| קרדינליות | N ראיות → ישות | N שינויים → ישות (לא חופף) |

מיזוג ייצור טבלה שבה מחצית העמודות NULL בכל שורה — בדיוק האנטי-דפוס שאתה מבקש להימנע ממנו. **ההפרדה כאן היא הבחנה מושגית אמיתית, לא פיצול שרירותי.**

### 4.8 `why_ron` → `fit_brief`

```sql
ALTER TABLE public.user_job_matches RENAME COLUMN why_ron TO fit_brief;
```

**תיקון להיקף שנרשם כאן במקור.** הגרסה הראשונה של הסעיף אמרה "106 שימושים ב-Backend, 0 ב-Frontend — שינוי פנימי לחלוטין". **זה היה שגוי.** הבדיקה רצה על `web_dashboard/src`, נתיב שמופיע ב-CLAUDE.md אבל **אינו קיים** — ה-Frontend נמצא ב-`frontend/`. `grep` על נתיב לא קיים מחזיר ריק, וזה נקרא בדיוק כמו "אין שימוש".

ההיקף האמיתי:

| שכבה | שימושים | קבצים |
|------|---------|-------|
| Backend | 113 | 19 |
| Frontend | 16 | 8 |
| חוזה API | `why_ron` הוא מפתח JSON ב-`JobMatch`, שמוחזר מ-5 ראוטים (`/feed`, `/{job_id}`, `/analyze`, ...) | |

ל-Frontend יש **שתי שכבות שמות** שצריכות לזוז יחד: `why_ron` בטיפוסי ה-wire (`apiTypes.ts`) ו-`whyRon` בטיפוס הדומיין הפנימי (`data.ts`, `JobCard.tsx`, `ReportDrawer.tsx`).

**המסקנה:** זה שינוי full-stack שחייב לצאת ב-PR אחד — Backend ו-Frontend לא יכולים להתפצל בין דיפלויים, אחרת ניתוח ה-AI ייעלם מכרטיסי המשרות.

**הלקח לתיעוד:** אין להסיק "לא בשימוש" מ-`grep` ריק בלי לוודא קודם שהנתיב קיים. `git ls-files | xargs grep` חסין לזה — הוא מחפש רק בקבצים שבאמת במעקב.

| נוכחי | יעד |
|-------|-----|
| `why_ron` (עמודה + מפתח JSON) | `fit_brief` |
| `whyRon` (טיפוס Frontend) | `fitBrief` |
| `update_why_ron()` | `update_fit_brief()` |
| `_WHY_RON_TEMPLATES` (matcher.py) | `_FIT_BRIEF_TEMPLATES` |
| `seed_ron_entities.py` | `seed_demo_entities.py` |

`tailor.py` כבר משתמש ב-`WHY_CANDIDATE:` בפרומפט — כלומר המינוח הנייטרלי כבר קיים בקוד, רק לא בסכימה.

### 4.9 `profile_answers` — מסלול הבגרות

הטבלה נשארת, אבל תפקידה מצטמצם ל**מה שהיא באמת טובה בו**: תשובות שאלון פתוחות שאין להן מבנה ידוע מראש.

| מפתח נוכחי | יעד |
|------------|-----|
| `career_goals` | → `user_preferences` (עמודות טיפוסיות) |
| `metrics_doc.metrics.*` | → נשאר (זה **באמת** Q&A פתוח) |
| `baseline_snapshot` | → מחושב מ-`profile_entities`, לא מאוחסן |
| `enriched_entities` | → `company_intel` (זה מידע על חברות!) |
| `user_persona` | → `profiles.persona JSONB` (1:1 עם משתמש) |
| `cv_data` | → כבר קיים ב-`cv_documents`+`profile_entities` — **למחיקה** |

אחרי הגריעה נשארת טבלה עם ייעוד יחיד וברור, לא "סל אשפה של JSON".

---

## 5. תוכנית ביצוע

חמישה שלבים, כל אחד קומיט עצמאי עם pytest ירוק, ובסדר מחייב.

### שלב 1 — סגירת פער הדיירות `[✅ בוצע · מיגרציה 00eab53e0f00]`

**תיקון לאפיון המקורי:** הסעיף הזה נכתב במקור כ"גיבוי 41 היתומים ומחיקתם". בדיקה פרטנית לפני הביצוע הראתה ש**זו הייתה הנחה שגויה — 36 מתוך 41 הם דאטה אמיתי**:

| היתום | שורות | האמת | פעולה שבוצעה |
|-------|-------|------|---------------|
| `…2aed67bcfede` | 13 | UUID עם **טעות הקלדה** בשני התווים האחרונים (`de` במקום `0e`). ראיות `cv_parse` ו-`conversation_star` אמיתיות, כולן מצביעות על ישויות של המשתמש האמיתי | הוצמדו ל-`…2aed67bcfe0e` |
| `default` | 23 | 10 שיחות Ariel אמיתיות (יוני-יולי 2026) + 13 מדידות shadow-score מעידן ה-single-user | הוצמדו לפרופיל הבעלים |
| `test_neg_cr_user` | 5 | fixture בדיקות אמיתי | נמחקו |

**הלקח לתיעוד:** "שורה יתומה" ≠ "זבל". לפני כל מחיקה מרוכזת יש לבדוק את התוכן בפועל — כאן מחיקה עיוורת הייתה משמידה ראיה STAR-מאומתת במשקל 65 ואת כל היסטוריית השיחות המוקדמת.

**מה בוצע בפועל:**
1. גיבוי כל 41 השורות ל-`backend/backups/orphan-rows-*.csv` (ב-`.gitignore` — מכיל תוכן שיחות אישי)
2. תיקון 36 שורות, מחיקת 5 → **0 יתומים**
3. הסרת `DEFAULT 'default'::text` מ-`applications.user_id` ומ-`profile_interviews.user_id` — שריד של עידן ה-single-user שחסם את שינוי הטיפוס
4. המרת `user_id` ל-`UUID` + FK CASCADE ב-14 טבלאות
5. 12 מודלי ORM הומרו לטיפוס דיאלקט-מותנה משותף:

```python
UUID_FK = String().with_variant(postgresql.UUID(as_uuid=False), "postgresql")
```

**למה לא `Uuid` הרגיל של SQLAlchemy — מלכודת שנתפסה בבדיקות:**

הניסיון הראשון השתמש ב-`Uuid(as_uuid=False)`, שנראה נכון: UUID ב-Postgres, מחרוזות ב-Python. הוא הפיל 5 בדיקות, והסיבה מלמדת משהו על הקוד הזה — **הוא מערבב `text()` גולמי עם קריאות ORM**.

`Uuid` מנרמל את שני הצדדים ל-hex-32 בלי מקפים. ב-Postgres זה לא מזיק (העמודה היא UUID אמיתי ו-PG מנרמל בעצמו), אבל ב-SQLite העמודה היא טקסט: `INSERT` גולמי כותב `'07ae21ec-998f-…'` עם מקפים, ושאילתת ORM מחפשת `'07ae21ec998f…'` בלי. **התוצאה: 0 שורות, בלי שגיאה.** כשל שקט.

הווריאנט פותר את זה בכך שהוא לא נוגע כלל בערך ב-SQLite — שני נתיבי הכתיבה מסכימים. ב-Postgres העמודה נשארת UUID אמיתי עם ה-FK.

**הכלל לעתיד:** כל עוד יש נתיבי `text()` גולמיים לצד ORM, טיפוס עמודה אסור לו לבצע נרמול ערכים בדיאלקט שבו העמודה היא טקסט.

**אימות:** FK-ים ל-`profiles` עלו מ-5 ל-**18**. הכנסה עם `user_id` לא קיים נדחית. `DELETE FROM profiles WHERE id=$1` מנקה **720 שורות ב-12 טבלאות** בפקודה אחת (נבדק בטרנזקציה עם rollback).

### שלב 2 — מינוח נייטרלי `[מהיר · סיכון אפסי]`
`why_ron` → `fit_brief` + שינויי השמות הנלווים. עצמאי לחלוטין, אפשר לבצע במקביל.

### שלב 3 — איחוד הפרופיל `[הרווח המוצרי הגדול ביותר]`
`cv_claims` → `profile_entities`, הרחבת הטקסונומיה, מחיקת הטבלה הממוזגת. עדכון `profile_repository.py` להחזיר כישורים עם ציון אמינות מובנה.

### שלב 4 — קונסולידציה של `user_job_matches` `[3 טבלאות פחות]`
קליטת `match_triggers`, `job_feedback`, `recruiter_reply_drafts` כעמודות + אינדקסים חלקיים.

### שלב 5 — איחוד השיחות `[הגדול ביותר · אחרון]`
`conversations` חדשה, הגירת 3 טבלאות אליה, `ariel_probe_log` → `conversation_events`.

**למה אחרון:** נוגע ב-Ariel שהיא הפיצ'ר הפעיל ביותר, ותלוי בכך ששלב 1 כבר ניקה את 10 השורות היתומות ב-`chat_sessions`.

### שלב 6 (אופציונלי) — בגרות `profile_answers`
לפי §4.9. לא חוסם שום דבר, מתאים כשיהיה שקט בפיצ'רים.

---

## 6. מה לא נוגעים בו — ולמה

| טבלה | ההחלטה |
|------|---------|
| `shadow_match_scores` | **נשארת.** כלי מדידה להשוואת גרסאות אלגוריתם — בדיוק כפי שביקשת. רק מקבלת FK תקין. |
| `company_intel` | **נשארת.** גלובלית, לא משתמש-תלויה — הפרדה נכונה (עיקרון 3: תחום בעלות שונה). |
| `all_jobs` | **נשארת נפרדת.** §4.4 — שלב קליטה, לא כפילות. |
| `evidence_records` + `confidence_audit_log` | **נשארות נפרדות.** §4.7 — קלט מול פלט. |
| `kv_store`, `alembic ×2` | **נשארות.** תשתית, מחוץ למודל התוכן. |

---

## 7. כלל עבודה להמשך

> **לפני כל פיצ'ר חדש שדורש אחסון, יש לענות על שלוש שאלות:**
>
> 1. **למי הנתון שייך?** אם למשתמש — `user_id UUID REFERENCES profiles(id) ON DELETE CASCADE`. אין חריגים.
> 2. **מה הקרדינליות?** 1:1 עם שורה קיימת → **עמודה**. 1:N אמיתי → טבלה חדשה.
> 3. **האם הישות כבר קיימת?** אם "כישור"/"משרה"/"שיחה" כבר מיוצגים — **מרחיבים**, לא מכפילים.
>
> טבלה חדשה שלא עוברת את שלוש השאלות — לא נכנסת לסכימה.

---

**מצב נוכחי:** 26 טבלאות · 18 FK ל-profiles · 0 שורות יתומות · שלב 1 הושלם
**מצב יעד:** 19 טבלאות · ~30 FK · 0 שורות יתומות · עוגן דיירות יחיד
