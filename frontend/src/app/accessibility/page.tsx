'use client'

import Link from 'next/link'
import { useI18n } from '@/contexts/I18nContext'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { TOKENS } from '@/lib/tokens'

// Content: bilingual, self-contained. Not part of the shared Dict type,
// since this is one standalone legal/informational page, not app chrome
// that needs the compile-time en/he parity check the Dict type enforces
// elsewhere.

const STATEMENT_DATE = 'August 21, 2026'
const STATEMENT_DATE_HE = '21 באוגוסט 2026'
const CONTACT_EMAIL = 'accessibility@jobapply.ai'

const content = {
  en: {
    eyebrow: 'Accessibility',
    title: 'Accessibility Statement',
    intro:
      'We want this site to work for everyone. That includes people using a screen reader, ' +
      'people who navigate by keyboard only, and people using other assistive technology. ' +
      'Here is what we have done, what is still not right, and how to tell us about a problem.',
    standardHeading: 'The standard we follow',
    standardBody:
      'We aim for WCAG 2.1 Level AA. That is also the technical basis of Israeli Standard ' +
      '(ת"י) 5568, the standard named in the Equal Rights for Persons with Disabilities ' +
      'Regulations (Service Accessibility Adjustments), 5773-2013.',
    doneHeading: 'What we have done',
    done: [
      'Every screen has real heading tags, not styled text that only looks like a heading. Screen readers can navigate by heading.',
      'Buttons that show only an icon (close, notifications, email setup, remove item) now carry a text label a screen reader can read.',
      'Pop-up windows like the outreach generator, the interview simulator, and the application detail panel are marked as real dialogs. Pressing Escape closes them, and opening one moves keyboard focus inside.',
      'Text colors meet the 4.5:1 contrast minimum required for normal-size text.',
      'Form fields are linked to their labels in code. Where a field shows an error message, the field is linked to that message too.',
      'Every image that carries information has real alt text. Purely decorative images are hidden from screen readers on purpose.',
      'The CV PDF you download is a tagged, structured document, not a flat picture of text. A screen reader can read it the way it reads the page.',
    ],
    limitationsHeading: 'What is still not right',
    limitations: [
      'On the first load of a page, a Hebrew visit briefly shows in English and left-to-right before switching to Hebrew. This flash is not good for screen reader users, and we have not fixed it yet.',
      'Keyboard focus does not fully stay inside an open dialog. Tab can still reach something behind it. Closing a dialog does not reliably send focus back to the button that opened it.',
      'Every page currently shares one browser tab title instead of its own.',
      'Most of the signed-in product (the dashboard, the job feed, the CV editor) is in English no matter which language you picked. Hebrew coverage there is not finished.',
    ],
    testingHeading: 'How we checked this',
    testingBody:
      `We checked this by reading the application's own source code against WCAG 2.1 AA, on ${STATEMENT_DATE}. ` +
      'This was a manual review of the code. It was not an automated scan, and no one using assistive ' +
      'technology has tested the site yet. We think of this as a starting point, not a finished job.',
    contactHeading: 'Tell us about a problem',
    contactBody:
      'If something on the site gets in your way, or if anything above does not match what you see, ' +
      'write to us. A person on the team reads every message.',
    contactCta: 'Email us',
    sizeNote:
      'JobApply is a small, early-stage team. Israeli law does not yet require us to name a formal ' +
      'accessibility coordinator at our size. The email above still reaches a real person.',
    backHome: '← Back to JobApply',
  },
  he: {
    eyebrow: 'נגישות',
    title: 'הצהרת נגישות',
    intro:
      'אנחנו רוצים שהאתר הזה יעבוד לכולם. זה כולל מי שמשתמש בקורא מסך, ' +
      'מי שמנווט רק במקלדת, ומי שמשתמש בטכנולוגיה מסייעת אחרת. ' +
      'הנה מה שעשינו, מה עדיין לא תקין, ואיך לספר לנו על בעיה.',
    standardHeading: 'התקן שאנחנו הולכים לפיו',
    standardBody:
      'אנחנו שואפים לעמוד ב-WCAG 2.1 ברמה AA. זה גם הבסיס הטכני של תקן ' +
      'ישראלי (ת"י) 5568, התקן שמוזכר בתקנות שוויון זכויות לאנשים עם מוגבלות ' +
      '(התאמות נגישות לשירות), תשע"ג-2013.',
    doneHeading: 'מה עשינו',
    done: [
      'לכל מסך יש תגי כותרת אמיתיים, לא טקסט מעוצב שרק נראה כמו כותרת. אפשר לנווט בין המסכים לפי כותרות עם קורא מסך.',
      'כפתורים שמציגים רק איקון (סגירה, התראות, חיבור מייל, הסרת פריט) קיבלו תווית טקסט שקורא מסך יכול לקרוא.',
      'חלונות קופצים כמו יצירת פנייה למעסיק, סימולטור הראיון, ופרטי המועמדות מסומנים כחלונות אמיתיים. לחיצה על Escape סוגרת אותם, ופתיחה מעבירה את הפוקוס במקלדת פנימה.',
      'צבעי הטקסט עומדים ביחס הניגודיות המינימלי של 4.5:1 שנדרש לטקסט בגודל רגיל.',
      'שדות טופס מקושרים בקוד לתווית שלהם. כשיש שדה עם הודעת שגיאה, השדה מקושר גם להודעה הזו.',
      'לכל תמונה שנושאת מידע יש טקסט חלופי אמיתי. תמונות עיצוביות בלבד מוסתרות מקוראי מסך בכוונה.',
      'קובץ ה-PDF של קורות החיים שאתם מורידים הוא מסמך מתוייג ומובנה, לא תמונה שטוחה של טקסט. קורא מסך יכול לקרוא אותו כמו שהוא קורא את העמוד.',
    ],
    limitationsHeading: 'מה עדיין לא תקין',
    limitations: [
      'בטעינה ראשונה של עמוד, כניסה בעברית מראה לרגע קצר אנגלית ומשמאל לימין לפני המעבר לעברית. ההבזק הזה לא טוב למשתמשי קורא מסך, ועדיין לא תיקנו אותו.',
      'פוקוס מקלדת לא נשאר לגמרי בתוך חלון פתוח. Tab עדיין יכול להגיע למשהו מאחוריו. סגירת חלון לא תמיד מחזירה את הפוקוס לכפתור שפתח אותו.',
      'כרגע לכל עמוד יש אותה כותרת טאב דפדפן, במקום כותרת משלו.',
      'רוב המוצר המאומת (לוח הבקרה, פיד המשרות, עורך קורות החיים) מוצג באנגלית בלי קשר לשפה שבחרתם. הכיסוי בעברית שם עוד לא גמור.',
    ],
    testingHeading: 'איך בדקנו את זה',
    testingBody:
      `בדקנו את זה בקריאה ישירה של קוד המקור של האפליקציה מול WCAG 2.1 AA, בתאריך ${STATEMENT_DATE_HE}. ` +
      'זו הייתה בדיקה ידנית של הקוד. זו לא הייתה סריקה אוטומטית, ואף אחד שמשתמש בטכנולוגיה מסייעת ' +
      'עוד לא בדק את האתר בפועל. אנחנו מתייחסים לזה כנקודת התחלה, לא כעבודה גמורה.',
    contactHeading: 'ספרו לנו על בעיה',
    contactBody:
      'אם משהו באתר מפריע לכם, או שמשהו למעלה לא תואם למה שאתם רואים, ' +
      'כתבו לנו. בן אדם מהצוות קורא כל הודעה.',
    contactCta: 'שלחו לנו מייל',
    sizeNote:
      'JobApply הוא צוות קטן בשלב מוקדם. החוק בישראל עדיין לא מחייב אותנו למנות רכז נגישות ' +
      'פורמלי בגודל הנוכחי שלנו. המייל למעלה עדיין מגיע לבן אדם אמיתי.',
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
              {c.contactCta}: {CONTACT_EMAIL}
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
