'use client'

import Link from 'next/link'
import { useI18n } from '@/contexts/I18nContext'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { TOKENS } from '@/lib/tokens'

// ── Content — bilingual, self-contained (not part of the shared Dict type:
// this is one standalone legal/informational page, not app chrome that needs
// the compile-time en/he parity check the Dict type enforces elsewhere). ──

const STATEMENT_DATE = 'August 21, 2026'
const STATEMENT_DATE_HE = '21 באוגוסט 2026'
const CONTACT_EMAIL = 'accessibility@jobapply.ai'

const content = {
  en: {
    eyebrow: 'Accessibility',
    title: 'Accessibility Statement',
    intro:
      'JobApply is committed to making its website usable by everyone, including people who ' +
      'use screen readers, keyboard-only navigation, or other assistive technology. This page ' +
      'describes what we’ve done, what we know still needs work, and how to reach us.',
    standardHeading: 'Standard we follow',
    standardBody:
      'We work toward WCAG 2.1 Level AA, which is also the technical basis of Israeli Standard ' +
      '(ת"י) 5568 — the standard referenced by the Equal Rights for Persons with Disabilities ' +
      'Regulations (Service Accessibility Adjustments), 5773-2013.',
    doneHeading: 'What we’ve done',
    done: [
      'Every screen has a real, programmatic heading structure (not just styled text) so screen-reader users can navigate by heading.',
      'Every icon-only button — close, notifications, email setup, remove-item — has a text label a screen reader can announce, not just a visual icon.',
      'Every pop-up dialog (job outreach, interview practice, CV brief, application detail, preferences panel, and more) is marked as a real dialog, closes on Escape, and moves keyboard focus into it when it opens.',
      'Text color combinations across the app meet the 4.5:1 contrast minimum for normal-size text.',
      'Form fields are programmatically linked to their labels and, where a field shows an inline error, to that error text.',
      'Every meaningful image has real alternative text; purely decorative images are hidden from screen readers on purpose.',
      'Downloaded CV/resume PDFs are exported as tagged, structured documents (not flat images of text), so a screen reader or other assistive tool can read them the same way it reads the on-screen version.',
    ],
    limitationsHeading: 'What we know still needs work',
    limitations: [
      'On first load, a Hebrew-language visit briefly renders in English/left-to-right before switching — the correct language loads a moment later, but that first flash isn’t ideal for screen-reader users.',
      'Keyboard focus does not yet fully cycle within an open dialog (Tab can reach elements behind it), and closing a dialog doesn’t yet reliably return focus to the button that opened it.',
      'Every page currently shares one generic browser-tab title rather than a page-specific one.',
      'Most of the authenticated product (the dashboard, job feed, CV editor) is presented in English regardless of your selected language — full Hebrew coverage of that part of the product is still in progress.',
    ],
    testingHeading: 'How this was checked',
    testingBody:
      `Checked by direct code review against WCAG 2.1 AA success criteria, dated ${STATEMENT_DATE}. ` +
      'This was a manual audit of the application’s source code, not an automated scan and not yet a ' +
      'test with actual assistive-technology users — we treat this as a floor, not a finished result.',
    contactHeading: 'Tell us about a problem',
    contactBody:
      'If you hit a barrier anywhere on the site, or something above doesn’t match what you’re seeing, ' +
      'please write to us — we read every message and it goes directly to the team building the product.',
    contactCta: 'Email us',
    sizeNote:
      'JobApply is an early-stage product from a small team. Israeli regulations don’t yet require us ' +
      'to appoint a formal accessibility coordinator at our current size — but the contact above reaches ' +
      'a real person regardless.',
    backHome: '← Back to JobApply',
  },
  he: {
    eyebrow: 'נגישות',
    title: 'הצהרת נגישות',
    intro:
      'ב-JobApply אנחנו מחויבים לכך שהאתר שלנו יהיה שמיש לכולם, כולל ' +
      'משתמשים בקורא מסך, ניווט במקלדת בלבד וטכנולוגיות מסייעת אחרות. דף ' +
      'זה מתאר מה עשינו, מה ידוע לנו שעדיין דורש עבודה, ואיך ליצור איתנו קשר.',
    standardHeading: 'התקן שלפיו אנו פועלים',
    standardBody:
      'אנחנו שואפים לעמוד ב-WCAG 2.1 ברמה AA, שהיא גם הבסיס הטכני של תקן ' +
      'ישראלי (ת"י) 5568 — התקן שאליו מפנות תקנות שוויון זכויות לאנשים עם מוגבלות ' +
      '(התאמות נגישות לשירות), תשע"ג-2013.',
    doneHeading: 'מה עשינו עד כה',
    done: [
      'לכל מסך יש מבנה כותרות מתכנתת אמיתי (לא רק טקסט מעוצב) כדי שמשתמשי קורא מסך יוכלו לנווט לפי כותרות.',
      'לכל כפתור עם איקונה בלבד — סגירה, התראות, חיבור מייל, הסרת פריט — יש תווית טקסט שקורא מסך יכול להכריז, ולא רק איקון ויזואלי.',
      'כל חלון קופץ (שיווק למעסיק, תרגול ראיון, תקציר קורות חיים, פרטי מועמדות ועוד) מסומן כחלון אמיתי, נסגר במקש Escape, ומעביר אליו פוקוס מקלדת עם הפתיחה.',
      'צירופי צבע באפליקציה עומדים ביחס אי ניגודיות מינימלי של 4.5:1 עבור טקסט בגודל רגיל.',
      'שדות טופס מקושרים אוטומטית לתוויות השלהם, וכאשר יש שגיאת שגיאה מובנית — גם לטקסט השגיאה עצמו.',
      'לכל תמונה משמעותית יש טקסט חלופי אמיתי; תמונות עיצוביות בלבד מוסתרות בכוונה מקוראי מסך.',
      'קובצי PDF של קורות חיים מיוצאים כמסמך מתוייג ומורכב (לא תמונה שטוחה של טקסט), כך שקורא מסך או כלי עזר אחר יכולים לקרוא אותם כמו את הגרסה שעל המסך.',
    ],
    limitationsHeading: 'מה אנחנו יודעים שעדיין דורש עבודה',
    limitations: [
      'בטעינה ראשונה, כניסה בעברית מציירת לרגע קצר באנגלית/משמאל לשמאל לפני המעבר לשפה הנכונה — לא אידיאלי למשתמשי קורא מסך.',
      'פוקוס מקלדת עדיין לא מסתובב במלואו בתוך דיאלוג פתוח (Tab יכול להגיע לאלמנטים מאחוריו), וסגירה של דיאלוג עדיין אינה מחזירה באופן אמין את הפוקוס לכפתור שפתח אותו.',
      'כרגע, לכל העמודים יש כותרת טאב דפדפן אחת וגנרית במקום כותרת ספציפית לעמוד.',
      'רוב המוצר המאומת (לוח הבקרה, פיד המשרות, עורך קורות החיים) מוצג באנגלית בלבד, ללא תלות בשפה שבחרת — כיסוי עברית מלא לחלק זה עדיין בעבודה.',
    ],
    testingHeading: 'איך בדקנו את זה',
    testingBody:
      `נבדק בבדיקת קוד ישירה מול מדדי WCAG 2.1 AA, נכון ${STATEMENT_DATE_HE}. ` +
      'זו בדיקה ידנית של קוד המקור של האפליקציה, לא סריקה אוטומטית ועדיין לא ' +
      'בדיקה עם משתמשים אמיתיים של טכנולוגיה מסייעת — אנחנו מתייחסים לזה כרצפה, לא כתוצאה סופית.',
    contactHeading: 'ספרו לנו על בעיה',
    contactBody:
      'אם נתקלתם במכשול כלשהו באתר, או שמשהו מהעל לא תואם למה שאתם רואים, ' +
      'אנא כתבו לנו — אנחנו קוראים כל הודעה והיא מגיעה ישירות לצוות שבונה את המוצר.',
    contactCta: 'שלחו לנו מייל',
    sizeNote:
      'JobApply הוא מוצר בשלב מוקדם של צוות קטנה. התקנות בישראל עדיין אינן מחייבות אותנו ' +
      'במינוי רכז נגישות פורמלי בגודל הנוכחי שלנו כרגע — אבל הפנייה למעלה מגיעה לאדם אמיתי בכל מקרה.',
    backHome: '→ חזרה ל-JobApply',
  },
} as const

export default function AccessibilityPage() {
  const { locale, dir } = useI18n()
  const c = content[locale]

  return (
    <div dir={dir} className="min-h-screen bg-ja-bg flex flex-col">
      {/* ── Top bar ── */}
      <header className="border-b border-slate-100 bg-white">
        <div className="max-w-[880px] mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="text-[15px] font-semibold text-slate-900 tracking-tight">
            JobApply
          </Link>
          <LanguageSwitcher />
        </div>
      </header>

      <main className="flex-1">
        <div className="max-w-[720px] mx-auto px-6 py-14">

          {/* ── Page header ── */}
          <div className="mb-10">
            <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-2">
              {c.eyebrow}
            </p>
            <h1 className="text-[28px] font-bold text-slate-900 tracking-tight leading-tight mb-4">
              {c.title}
            </h1>
            <p className="text-[14px] text-slate-600 leading-relaxed max-w-[62ch]">
              {c.intro}
            </p>
          </div>

          {/* ── Standard ── */}
          <section className="py-7 border-t border-slate-100">
            <h2 className="text-[13px] font-bold text-slate-900 mb-2.5">{c.standardHeading}</h2>
            <p className="text-[13.5px] text-slate-600 leading-relaxed max-w-[62ch]">
              {c.standardBody}
            </p>
          </section>

          {/* ── Done ── */}
          <section className="py-7 border-t border-slate-100">
            <h2 className="text-[13px] font-bold text-slate-900 mb-4">{c.doneHeading}</h2>
            <ul className="space-y-3">
              {c.done.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <span
                    aria-hidden="true"
                    className="mt-[7px] w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ background: TOKENS.color.primary }}
                  />
                  <span className="text-[13.5px] text-slate-600 leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          </section>

          {/* ── Limitations ── */}
          <section className="py-7 border-t border-slate-100">
            <h2 className="text-[13px] font-bold text-slate-900 mb-4">{c.limitationsHeading}</h2>
            <ul className="space-y-3">
              {c.limitations.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <span
                    aria-hidden="true"
                    className="mt-[7px] w-1.5 h-1.5 rounded-full shrink-0 bg-slate-300"
                  />
                  <span className="text-[13.5px] text-slate-600 leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          </section>

          {/* ── Testing ── */}
          <section className="py-7 border-t border-slate-100">
            <h2 className="text-[13px] font-bold text-slate-900 mb-2.5">{c.testingHeading}</h2>
            <p className="text-[13.5px] text-slate-600 leading-relaxed max-w-[62ch]">
              {c.testingBody}
            </p>
          </section>

          {/* ── Contact ── */}
          <section className="py-7 border-t border-slate-100">
            <h2 className="text-[13px] font-bold text-slate-900 mb-2.5">{c.contactHeading}</h2>
            <p className="text-[13.5px] text-slate-600 leading-relaxed max-w-[62ch] mb-4">
              {c.contactBody}
            </p>
            <a
              href={`mailto:${CONTACT_EMAIL}`}
              className="inline-flex items-center h-10 px-4 rounded-lg text-[13px] font-semibold text-white transition-colors"
              style={{ background: TOKENS.color.primary }}
              onMouseEnter={e => { e.currentTarget.style.background = TOKENS.color.primaryHover }}
              onMouseLeave={e => { e.currentTarget.style.background = TOKENS.color.primary }}
            >
              {c.contactCta} — {CONTACT_EMAIL}
            </a>
            <p className="text-[12px] text-slate-400 leading-relaxed mt-5 max-w-[62ch]">
              {c.sizeNote}
            </p>
          </section>

          <div className="pt-4">
            <Link href="/" className="text-[13px] font-medium text-teal-700 hover:text-teal-800 transition-colors">
              {c.backHome}
            </Link>
          </div>

        </div>
      </main>
    </div>
  )
}
