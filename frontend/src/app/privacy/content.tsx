'use client'

import { LegalPage } from '@/components/legal/LegalPage'
import { useI18n } from '@/contexts/I18nContext'

/**
 * Privacy policy, one version per language.
 *
 * The prose lives here as JSX rather than in the locale dictionaries on
 * purpose. These are ~450 words of legal text that a lawyer still has to
 * review (see the draft banner), and text that has to be reviewed has to be
 * readable — as escaped one-line strings in he.ts it would be neither
 * reviewable nor diffable, and a reviewer would be reading the wrong artifact.
 *
 * The English text is the authoritative version. The Hebrew is a translation
 * provided so Hebrew-speaking users can understand what they are agreeing to;
 * where the two disagree, English governs, and the Hebrew says so at the end.
 * That is the normal arrangement for a translated policy and it matters here,
 * because a translation can drift from the original on a later edit.
 */
export function PrivacyContent() {
  const { locale, t } = useI18n()
  const L = t.legal

  if (locale === 'he') {
    return (
      <LegalPage title={L.privacy_title} updated={L.updated_date}>
        <h2>מה אנחנו אוספים</h2>
        <ul>
          <li><strong>פרטי חשבון</strong> — כתובת מייל ושם, מהרשמה עם מייל וסיסמה או מכניסה עם Google.</li>
          <li><strong>נתוני הקריירה שלכם</strong> — כל מה שאתם מספקים כדי לבנות את הפרופיל: היסטוריה
            תעסוקתית, השכלה, מיומנויות, קורות חיים שהעליתם, ומידע שיובא מ-LinkedIn אם בחרתם לחבר אותו.</li>
          <li><strong>פעילות הגשה</strong> — המשרות שצפיתם בהן, שמרתם או הגשתם אליהן, והסטטוס שלהן
            ככל שאתם (או מייל ממגייס שהועבר, אם הפעלתם זאת) מעדכנים אותו.</li>
          <li><strong>שיחות עם עוזר ה-AI</strong> — הודעות שאתם שולחים לאריאל וההקשר הדרוש כדי לענות עליהן.</li>
          <li><strong>נתוני שימוש בסיסיים</strong> — מה שכל אפליקציית ווב אוספת כדי לתפקד (חותמות זמן,
            לוגים של שגיאות, ספירות פעילות גסות).</li>
        </ul>

        <h2>איך אנחנו משתמשים בזה</h2>
        <ul>
          <li>כדי לייצר קורות חיים מותאמים, ציוני התאמה והודעות פנייה שמותאמים לכם ולמשרה ספציפית.</li>
          <li>כדי להפעיל את פיד המשרות ולהתאים אתכם למשרות חדשות.</li>
          <li>כדי להפעיל את עוזר ה-AI.</li>
          <li>כדי לתחזק ולשפר את השירות (איתור תקלות, מניעת שימוש לרעה).</li>
        </ul>
        <p>אנחנו לא מוכרים את הנתונים שלכם.</p>

        <h2>מי עוד רואה את זה</h2>
        <ul>
          <li><strong>Anthropic, ובמקומות שבהם זה מופעל גם Google</strong> — מעבדים את הפרופיל ואת
            תוכן המשרה כדי לייצר קורות חיים, ציונים ותשובות צ׳אט. הם מקבלים את מה שנדרש לבקשה
            הספציפית, לא את כל החשבון שלכם.</li>
          <li><strong>Supabase</strong> — מארחת את מסד הנתונים ומטפלת בהתחברות. נתוני החשבון והפרופיל
            שלכם נמצאים שם.</li>
          <li>איננו משתפים את הנתונים שלכם עם מעסיקים או צדדים שלישיים לצורכי שיווק. קורות חיים
            מותאמים נשלחים רק לאן שאתם בוחרים לשלוח אותם.</li>
        </ul>

        <h2>עיבוד באמצעות AI</h2>
        <p>
          הפקת קורות חיים מותאמים, ציון התאמה או תשובת צ׳אט משמעה שליחת חלקים רלוונטיים מהפרופיל
          שלכם לספק AI — כיום Anthropic, ו-Google במקומות שבהם הספק מופעל — עבור אותה בקשה
          ספציפית. כרגע איננו מציעים דרך להשתמש בפיצ׳רי הליבה של JobApply בלי זה.
        </p>

        <h2>הבחירות שלכם</h2>
        <ul>
          <li>אתם יכולים לערוך או למחוק שדות פרופיל, רשומות בקורות החיים ורשומות הגשה מתוך המוצר.</li>
          <li>
            מחיקת חשבון מלאה וייצוא מלא של הנתונים אינם זמינים עדיין כפעולות עצמאיות —{' '}
            <strong>אם אתם רוצים אחד מהם, פנו אלינו ישירות</strong> ונטפל בזה ידנית בזמן שהיכולת הזו
            נבנית.
          </li>
        </ul>

        <h2>אבטחה</h2>
        <p>
          הסשן שלכם מאומת באמצעות טוקנים חתומים, ונתוני האפליקציה מוגבלים לחשבון שלכם. כמו בכל שירות
          מקוון, אף מערכת אינה מאובטחת לחלוטין, ואיננו יכולים להבטיח הגנה מוחלטת מפני כל התקפה אפשרית.
        </p>

        <h2>שינויים</h2>
        <p>
          ייתכן שנעדכן את המדיניות הזו ככל שהמוצר משתנה. שינויים מהותיים יופיעו כאן עם תאריך מעודכן.
        </p>

        <h2>יצירת קשר</h2>
        <p>
          שאלות על המדיניות הזו, או בקשה למחוק את החשבון או לייצא את הנתונים:{' '}
          <a href="mailto:support@jobapply.ai">support@jobapply.ai</a>.
        </p>

        <h2>שפה מחייבת</h2>
        <p>
          הנוסח האנגלי של מדיניות זו הוא הנוסח המחייב. התרגום לעברית ניתן לנוחותכם, ובמקרה של סתירה
          בין הנוסחים — הנוסח האנגלי גובר.
        </p>
      </LegalPage>
    )
  }

  return (
    <LegalPage title={L.privacy_title} updated={L.updated_date}>
      <h2>What we collect</h2>
      <ul>
        <li><strong>Account info</strong> — email address and name, from email/password sign-up
          or Google sign-in.</li>
        <li><strong>Your career data</strong> — anything you provide to build your profile: work
          history, education, skills, uploaded CVs, and information imported from LinkedIn if you
          choose to connect it.</li>
        <li><strong>Application activity</strong> — the jobs you view, save, or apply to, and the
          status of those applications as you (or, if enabled, a forwarded recruiter email) update them.</li>
        <li><strong>Conversations with the AI assistant</strong> — messages you send to Ariel and
          the context needed to answer them.</li>
        <li><strong>Basic usage data</strong> — the kind any web app collects to keep the service
          running (timestamps, error logs, rough activity counts).</li>
      </ul>

      <h2>How we use it</h2>
      <ul>
        <li>To generate tailored CVs, fit scores, and outreach messages personalized to you and a
          specific job.</li>
        <li>To run your job feed and match you against new postings.</li>
        <li>To operate the AI assistant.</li>
        <li>To maintain and improve the service (debugging, abuse prevention).</li>
      </ul>
      <p>We do not sell your data.</p>

      <h2>Who else sees it</h2>
      <ul>
        <li><strong>Anthropic and, where enabled, Google</strong> — process your profile and job
          content to generate CVs, scores, and chat replies. They receive what&apos;s needed for
          that specific request, not your full account.</li>
        <li><strong>Supabase</strong> — hosts our database and handles authentication. Your
          account and profile data lives there.</li>
        <li>We don&apos;t share your data with employers or third parties for marketing. A
          tailored CV is only sent where you choose to send it.</li>
      </ul>

      <h2>AI processing</h2>
      <p>
        Generating a tailored CV, a match score, or a chat reply means sending relevant parts of
        your profile to an AI provider — currently Anthropic, and Google where that provider is
        enabled — for that specific request. We don&apos;t currently offer a way to use
        JobApply&apos;s core features without this.
      </p>

      <h2>Your choices</h2>
      <ul>
        <li>You can edit or delete individual profile fields, CV entries, and application records
          from within the product.</li>
        <li>
          Full account deletion and a complete data export are not yet available as self-service
          actions — <strong>if you want either, contact us directly</strong> and we&apos;ll handle
          it manually while that capability is being built.
        </li>
      </ul>

      <h2>Security</h2>
      <p>
        Your session is authenticated via signed tokens; application data is scoped to your
        account. As with any online service, no system is perfectly secure, and we can&apos;t
        guarantee absolute protection against every possible attack.
      </p>

      <h2>Changes</h2>
      <p>
        We may update this policy as the product changes. Material changes will be reflected here
        with an updated date.
      </p>

      <h2>Contact</h2>
      <p>
        Questions about this policy, or a request to delete your account or export your data:{' '}
        <a href="mailto:support@jobapply.ai">support@jobapply.ai</a>.
      </p>
    </LegalPage>
  )
}
