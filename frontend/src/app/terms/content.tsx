'use client'

import { LegalPage } from '@/components/legal/LegalPage'
import { useI18n } from '@/contexts/I18nContext'
import { CONTACT_EMAIL } from '@/lib/contact'

/** See content.tsx under /privacy for why the prose lives here rather than in
 *  the locale dictionaries, and why English is the governing version. */
export function TermsContent() {
  const { locale, t } = useI18n()
  const L = t.legal
  const mail = <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>

  if (locale === 'he') {
    return (
      <LegalPage title={L.terms_title} updated={L.updated_date}>
        <h2>מה JobApply עושה</h2>
        <p>
          JobApply עוזרת לכם להגיש מועמדות למשרות. אתם מוסרים את הניסיון שלכם ובוחרים משרה,
          והמערכת מכינה קורות חיים מותאמים, ציון התאמה למשרה וכלים למעקב אחרי ההגשות. אריאל,
          העוזרת באתר, עונה על שאלות לגבי הפרופיל שלכם ולגבי משרות.
        </p>

        <h2>החשבון שלכם</h2>
        <ul>
          <li>כדי להשתמש באתר צריך חשבון, במייל וסיסמה או בכניסה עם Google.</li>
          <li>אתם אחראים לשמור על פרטי הכניסה ועל מה שנעשה בחשבון שלכם.</li>
          <li>הפרטים שאתם מוסרים על הניסיון שלכם צריכים להיות נכונים. קורות חיים עם מידע לא נכון
            עלולים לפגוע בכם מול מעסיקים.</li>
        </ul>

        <h2>תוכן שנוצר ב-AI</h2>
        <ul>
          <li>קורות חיים, ציוני התאמה, הודעות פנייה ותשובות של אריאל נוצרים על ידי מודלי AI של
            Google ו-Anthropic, על סמך מה שמסרתם.</li>
          <li>תוכן כזה יכול לטעות. קראו כל מסמך לפני ששולחים אותו למעסיק: אתם מגישים אותו, ואתם
            אחראים לנכונות שלו.</li>
          <li>האתר בודק אוטומטית שהתוכן נשען על מה שמסרתם, אבל הבדיקות האלה לא מושלמות.</li>
        </ul>

        <h2>שימוש מותר</h2>
        <p>אסור להשתמש ב-JobApply כדי:</p>
        <ul>
          <li>למסור למעסיק מידע שאתם יודעים שאינו נכון.</li>
          <li>לשבש את השירות, להעמיס עליו או להשיג אליו גישה בלי הרשאה.</li>
          <li>לאסוף, למכור או להפיץ נתוני משרות או תוכן שנוצר באתר, מעבר לשימוש אישי.</li>
        </ul>

        <h2>מידע על משרות וחברות</h2>
        <p>
          המשרות באתר נאספות מלוחות דרושים ציבוריים וממקורות נוספים. אנחנו לא שולטים בדיוק שלהן,
          ומשרה שמופיעה אצלכם לא בהכרח עדיין פתוחה או מתוארת נכון במקור.
        </p>

        <h2>ללא התחייבות</h2>
        <p>
          השירות ניתן כמו שהוא. אנחנו לא מתחייבים שתקבלו ראיונות או הצעות, שהשירות יפעל בלי
          הפסקות, או שתוכן שנוצר ב-AI יהיה בלי טעויות.
        </p>

        <h2>עדכונים לתנאים</h2>
        <p>כשנשנה משהו מהותי, הוא יופיע כאן עם תאריך עדכון חדש.</p>

        <h2>יצירת קשר</h2>
        <p>שאלות על התנאים: {mail}</p>

        <h2>הנוסח המחייב</h2>
        <p>הנוסח באנגלית הוא המחייב. אם יש סתירה בינו לבין התרגום הזה, הנוסח באנגלית קובע.</p>
      </LegalPage>
    )
  }

  return (
    <LegalPage title={L.terms_title} updated={L.updated_date}>
      <h2>What JobApply does</h2>
      <p>
        JobApply helps you apply for jobs. You give it your experience and pick a job, and it
        prepares a tailored CV, a fit score for the job and tools to track your applications.
        Ariel, the assistant on the site, answers questions about your profile and about jobs.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>You need an account to use the site, with email and password or Google sign-in.</li>
        <li>You are responsible for keeping your sign-in details safe and for what is done in
          your account.</li>
        <li>What you tell us about your experience must be true. A CV with false information can
          hurt you with employers.</li>
      </ul>

      <h2>AI-generated content</h2>
      <ul>
        <li>CVs, fit scores, outreach messages and replies from Ariel are written by AI models
          from Google and Anthropic, based on what you gave us.</li>
        <li>This content can be wrong. Read every document before you send it to an employer: you
          are the one submitting it, and you are responsible for its accuracy.</li>
        <li>The site checks automatically that generated content rests on what you told us, but
          those checks are not perfect.</li>
      </ul>

      <h2>Acceptable use</h2>
      <p>Do not use JobApply to:</p>
      <ul>
        <li>Give an employer information you know is false.</li>
        <li>Disrupt or overload the service, or access it without permission.</li>
        <li>Collect, sell or redistribute job data or generated content beyond personal use.</li>
      </ul>

      <h2>Job and company information</h2>
      <p>
        Jobs on the site are collected from public job boards and other sources. We do not control
        their accuracy, and a job in your feed may no longer be open or may be described
        differently at the source.
      </p>

      <h2>No warranty</h2>
      <p>
        The service is provided as is. We do not promise that you will get interviews or offers,
        that the service will run without interruption, or that AI-generated content will be free
        of mistakes.
      </p>

      <h2>Changes to these terms</h2>
      <p>When we change something material, it will appear here with a new date.</p>

      <h2>Contact</h2>
      <p>Questions about these terms: {mail}</p>
    </LegalPage>
  )
}
