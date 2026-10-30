'use client'

import { LegalPage } from '@/components/legal/LegalPage'
import { useI18n } from '@/contexts/I18nContext'
import { CONTACT_EMAIL } from '@/lib/contact'

/**
 * Privacy policy, one version per language.
 *
 * The prose lives here as JSX rather than in the locale dictionaries on
 * purpose: it is legal text a lawyer still has to review (see the draft
 * banner), and as escaped one-line strings in he.ts it would be neither
 * readable nor diffable.
 *
 * The English text is the governing version; the Hebrew says so at the end.
 * Written plainly, without dashes and filler: the founder asked that nothing
 * on the site read as machine-written.
 */
export function PrivacyContent() {
  const { locale, t } = useI18n()
  const L = t.legal
  const mail = <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>

  if (locale === 'he') {
    return (
      <LegalPage title={L.privacy_title} updated={L.updated_date}>
        <h2>אילו נתונים אנחנו שומרים</h2>
        <ul>
          <li><strong>פרטי חשבון:</strong> כתובת מייל ושם, מההרשמה במייל וסיסמה או מהכניסה עם Google.</li>
          <li><strong>נתוני קריירה:</strong> מה שמסרתם לבניית הפרופיל, כמו ניסיון תעסוקתי, השכלה,
            כישורים וקורות חיים שהעליתם.</li>
          <li><strong>פעילות הגשה:</strong> משרות שצפיתם בהן, שמרתם או הגשתם אליהן, והסטטוס שעדכנתם.</li>
          <li><strong>שיחות עם אריאל:</strong> ההודעות שאתם שולחים לעוזרת, והמידע שהיא צריכה כדי לענות.</li>
          <li><strong>נתוני שימוש בסיסיים:</strong> זמני פעולות ויומני שגיאות, כמו בכל אתר.</li>
        </ul>

        <h2>למה אנחנו משתמשים בהם</h2>
        <ul>
          <li>להכין קורות חיים מותאמים, ציוני התאמה והודעות פנייה למשרה מסוימת.</li>
          <li>למצוא לכם משרות חדשות שמתאימות לפרופיל.</li>
          <li>להפעיל את אריאל.</li>
          <li>לתקן תקלות ולמנוע שימוש לרעה.</li>
        </ul>
        <p>אנחנו לא מוכרים את הנתונים שלכם.</p>

        <h2>מי עוד מקבל גישה</h2>
        <ul>
          <li><strong>Google ו-Anthropic:</strong> ספקי ה-AI שלנו. כשאתם מבקשים קורות חיים, ציון או
            תשובה בצ׳אט, הם מקבלים את החלק בפרופיל ובמשרה שנדרש לבקשה הזו בלבד.</li>
          <li><strong>Supabase:</strong> מארחת את מסד הנתונים ואת מערכת ההתחברות.</li>
          <li>אנחנו לא מעבירים נתונים למעסיקים או לגורמי שיווק. קורות חיים נשלחים רק למי שאתם
            בוחרים לשלוח אליו.</li>
        </ul>

        <h2>שימוש ב-AI</h2>
        <p>
          כל קורות חיים, ציון התאמה או תשובה של אריאל נוצרים על ידי ספק AI, ולכן חלקים מהפרופיל
          נשלחים אליו לצורך הבקשה. אי אפשר כרגע להשתמש בפעולות האלה בלי זה.
        </p>

        <h2>מה אפשר לעשות עם הנתונים</h2>
        <ul>
          <li>לערוך או למחוק פרטים בפרופיל, בקורות החיים וברשימת ההגשות, מתוך האתר.</li>
          <li>למחוק את החשבון כולו או לקבל עותק של כל הנתונים: עדיין אין לזה כפתור באתר. כתבו
            לנו ונטפל בזה ידנית.</li>
        </ul>

        <h2>אבטחה</h2>
        <p>
          ההתחברות מאומתת בטוקנים חתומים, וכל משתמש רואה רק את הנתונים שלו. אף מערכת מקוונת
          אינה חסינה לחלוטין, ואנחנו לא יכולים להבטיח הגנה מכל מתקפה.
        </p>

        <h2>עדכונים למדיניות</h2>
        <p>כשנשנה משהו מהותי, הוא יופיע כאן עם תאריך עדכון חדש.</p>

        <h2>יצירת קשר</h2>
        <p>שאלות על המדיניות, או בקשה למחיקת החשבון או לעותק של הנתונים: {mail}</p>

        <h2>הנוסח המחייב</h2>
        <p>הנוסח באנגלית הוא המחייב. אם יש סתירה בינו לבין התרגום הזה, הנוסח באנגלית קובע.</p>
      </LegalPage>
    )
  }

  return (
    <LegalPage title={L.privacy_title} updated={L.updated_date}>
      <h2>What we keep</h2>
      <ul>
        <li><strong>Account details:</strong> your email address and name, from email sign-up or
          Google sign-in.</li>
        <li><strong>Career data:</strong> what you give us to build your profile, such as work
          history, education, skills and the CVs you upload.</li>
        <li><strong>Application activity:</strong> the jobs you view, save or apply to, and the
          status you set on them.</li>
        <li><strong>Conversations with Ariel:</strong> the messages you send the assistant and the
          information it needs to answer.</li>
        <li><strong>Basic usage data:</strong> timestamps and error logs, as on any website.</li>
      </ul>

      <h2>Why we use it</h2>
      <ul>
        <li>To write tailored CVs, fit scores and outreach messages for a specific job.</li>
        <li>To find new jobs that match your profile.</li>
        <li>To run Ariel.</li>
        <li>To fix problems and prevent abuse.</li>
      </ul>
      <p>We do not sell your data.</p>

      <h2>Who else has access</h2>
      <ul>
        <li><strong>Google and Anthropic:</strong> our AI providers. When you ask for a CV, a score
          or a chat reply, they receive only the parts of your profile and the job that the
          request needs.</li>
        <li><strong>Supabase:</strong> hosts our database and our sign-in system.</li>
        <li>We do not pass your data to employers or marketers. A CV goes only where you choose
          to send it.</li>
      </ul>

      <h2>AI processing</h2>
      <p>
        Every CV, fit score and reply from Ariel is produced by an AI provider, so the relevant
        parts of your profile are sent to it for that request. These features cannot be used
        without that.
      </p>

      <h2>Your choices</h2>
      <ul>
        <li>You can edit or delete details in your profile, your CVs and your applications from
          within the site.</li>
        <li>Deleting your whole account, or getting a copy of all your data, has no button yet.
          Write to us and we will do it for you.</li>
      </ul>

      <h2>Security</h2>
      <p>
        Sign-in is verified with signed tokens, and each user sees only their own data. No online
        system is completely secure, and we cannot promise protection from every attack.
      </p>

      <h2>Changes to this policy</h2>
      <p>When we change something material, it will appear here with a new date.</p>

      <h2>Contact</h2>
      <p>Questions about this policy, or a request to delete your account or get your data: {mail}</p>
    </LegalPage>
  )
}
