/**
 * Role suggestions for the onboarding role picker, in English and Hebrew.
 *
 * The list used to be ~40 English tech/startup titles. An insurance agent or
 * a pension advisor typing "סוכן ביטוח" found nothing and concluded the
 * product was not for them. It now covers the Israeli job market broadly and
 * matches either language.
 *
 * `en` is what gets stored: the profile is canonically English (backend
 * migration c5a91b3e7d02), and services/user_title_terms.py expands each
 * stored title into English and Hebrew search terms. `he` is display and
 * search only. A role typed by hand is still accepted as-is, in any language.
 */
export interface RoleOption {
  en: string
  he: string
}

export const ROLE_CATALOG: readonly RoleOption[] = [
  // Tech & product
  { en: 'Software Engineer',                he: 'מהנדס/ת תוכנה' },
  { en: 'Backend Developer',                he: 'מפתח/ת Backend' },
  { en: 'Frontend Developer',               he: 'מפתח/ת Frontend' },
  { en: 'Full Stack Developer',             he: 'מפתח/ת Full Stack' },
  { en: 'Mobile Developer',                 he: 'מפתח/ת מובייל' },
  { en: 'DevOps Engineer',                  he: 'מהנדס/ת DevOps' },
  { en: 'QA Engineer',                      he: 'בודק/ת תוכנה (QA)' },
  { en: 'Data Analyst',                     he: 'אנליסט/ית נתונים' },
  { en: 'Data Scientist',                   he: 'מדען/ית נתונים' },
  { en: 'Data Engineer',                    he: 'מהנדס/ת נתונים' },
  { en: 'Machine Learning Engineer',        he: 'מהנדס/ת למידת מכונה' },
  { en: 'Security Engineer',                he: 'מהנדס/ת אבטחת מידע' },
  { en: 'IT Manager',                       he: 'מנהל/ת מערכות מידע' },
  { en: 'System Administrator',             he: 'מנהל/ת רשת ומערכות' },
  { en: 'Technical Support Engineer',       he: 'תמיכה טכנית' },
  { en: 'Solutions Architect',              he: 'ארכיטקט/ית פתרונות' },
  { en: 'Engineering Manager',              he: 'מנהל/ת פיתוח' },
  { en: 'Product Manager',                  he: 'מנהל/ת מוצר' },
  { en: 'Product Analyst',                  he: 'אנליסט/ית מוצר' },
  { en: 'Product Designer',                 he: 'מעצב/ת מוצר' },
  { en: 'UX Designer',                      he: 'מעצב/ת UX' },
  { en: 'UX Researcher',                    he: 'חוקר/ת UX' },
  { en: 'Graphic Designer',                 he: 'מעצב/ת גרפי/ת' },
  { en: 'Technical Writer',                 he: 'כותב/ת טכני/ת' },
  { en: 'Project Manager',                  he: 'מנהל/ת פרויקטים' },
  { en: 'Program Manager',                  he: 'מנהל/ת תוכניות' },
  // Insurance & finance
  { en: 'Insurance Agent',                  he: 'סוכן/ת ביטוח' },
  { en: 'Pension Advisor',                  he: 'יועץ/ת פנסיוני/ת' },
  { en: 'Financial Planner',                he: 'מתכנן/ת פיננסי/ת' },
  { en: 'Insurance Underwriter',            he: 'חתם/ת ביטוח' },
  { en: 'Insurance Claims Adjuster',        he: 'מסלק/ת תביעות ביטוח' },
  { en: 'Investment Advisor',               he: 'יועץ/ת השקעות' },
  { en: 'Bank Teller',                      he: 'טלר/ית בבנק' },
  { en: 'Banker',                           he: 'בנקאי/ת' },
  { en: 'Mortgage Advisor',                 he: 'יועץ/ת משכנתאות' },
  { en: 'Accountant',                       he: 'רואה/ת חשבון' },
  { en: 'Bookkeeper',                       he: 'מנהל/ת חשבונות' },
  { en: 'Payroll Specialist',               he: 'חשב/ת שכר' },
  { en: 'Controller',                       he: 'חשב/ת (קונטרולר/ית)' },
  { en: 'Financial Analyst',                he: 'אנליסט/ית פיננסי/ת' },
  { en: 'Finance Manager',                  he: 'מנהל/ת כספים' },
  { en: 'CFO',                              he: 'סמנכ"ל/ית כספים' },
  { en: 'Economist',                        he: 'כלכלן/ית' },
  { en: 'Actuary',                          he: 'אקטואר/ית' },
  { en: 'Compliance Officer',               he: 'קצין/ת ציות' },
  { en: 'Risk Manager',                     he: 'מנהל/ת סיכונים' },
  // Sales, service & business
  { en: 'Sales Representative',             he: 'נציג/ת מכירות' },
  { en: 'Sales Manager',                    he: 'מנהל/ת מכירות' },
  { en: 'Account Manager',                  he: 'מנהל/ת לקוחות' },
  { en: 'Account Executive',                he: 'איש/אשת מכירות (Account Executive)' },
  { en: 'Sales Development Representative', he: 'פיתוח עסקי (SDR)' },
  { en: 'Business Development Manager',     he: 'מנהל/ת פיתוח עסקי' },
  { en: 'Customer Service Representative',  he: 'נציג/ת שירות לקוחות' },
  { en: 'Customer Success Manager',         he: 'מנהל/ת הצלחת לקוחות' },
  { en: 'Call Center Representative',       he: 'נציג/ת מוקד' },
  { en: 'Telemarketer',                     he: 'טלפן/ית' },
  { en: 'Retention Representative',         he: 'נציג/ת שימור' },
  { en: 'Partnership Manager',              he: 'מנהל/ת שותפויות' },
  { en: 'Business Analyst',                 he: 'אנליסט/ית עסקי/ת' },
  { en: 'Operations Manager',               he: 'מנהל/ת תפעול' },
  { en: 'Chief of Staff',                   he: 'ראש/ת מטה' },
  { en: 'General Manager',                  he: 'מנכ"ל/ית' },
  { en: 'Branch Manager',                   he: 'מנהל/ת סניף' },
  { en: 'Store Manager',                    he: 'מנהל/ת חנות' },
  { en: 'Sales Associate',                  he: 'מוכר/ת' },
  { en: 'Cashier',                          he: 'קופאי/ת' },
  { en: 'Real Estate Agent',                he: 'מתווך/ת נדל"ן' },
  { en: 'Procurement Manager',              he: 'מנהל/ת רכש' },
  { en: 'Buyer',                            he: 'קניין/ית' },
  // Marketing & content
  { en: 'Marketing Manager',                he: 'מנהל/ת שיווק' },
  { en: 'Digital Marketing Manager',        he: 'מנהל/ת שיווק דיגיטלי' },
  { en: 'Content Writer',                   he: 'כותב/ת תוכן' },
  { en: 'Copywriter',                       he: 'קופירייטר/ית' },
  { en: 'Social Media Manager',             he: 'מנהל/ת סושיאל' },
  { en: 'Product Marketing Manager',        he: 'מנהל/ת שיווק מוצר' },
  { en: 'Growth Manager',                   he: 'מנהל/ת צמיחה' },
  { en: 'Public Relations Manager',         he: 'יחצ"ן/ית' },
  { en: 'Spokesperson',                     he: 'דובר/ת' },
  { en: 'Marketing Director',               he: 'סמנכ"ל/ית שיווק' },
  // Administration, HR & legal
  { en: 'Office Manager',                   he: 'מנהל/ת משרד' },
  { en: 'Administrative Assistant',         he: 'מזכיר/ה' },
  { en: 'Executive Assistant',              he: 'עוזר/ת אישי/ת' },
  { en: 'Receptionist',                     he: 'פקיד/ת קבלה' },
  { en: 'Data Entry Clerk',                 he: 'קלדן/ית' },
  { en: 'Back Office Clerk',                he: 'עובד/ת בק אופיס' },
  { en: 'HR Manager',                       he: 'מנהל/ת משאבי אנוש' },
  { en: 'HR Business Partner',              he: 'שותף/ה עסקי/ת משאבי אנוש (HRBP)' },
  { en: 'Recruiter',                        he: 'רכז/ת גיוס' },
  { en: 'Talent Acquisition Manager',       he: 'מנהל/ת גיוס' },
  { en: 'Lawyer',                           he: 'עורך/ת דין' },
  { en: 'Legal Counsel',                    he: 'יועץ/ת משפטי/ת' },
  { en: 'Paralegal',                        he: 'מתמחה / עוזר/ת משפטי/ת' },
  { en: 'Legal Secretary',                  he: 'מזכיר/ה משפטי/ת' },
  // Healthcare & welfare
  { en: 'Registered Nurse',                 he: 'אח/ות מוסמך/ת' },
  { en: 'Physician',                        he: 'רופא/ה' },
  { en: 'Pharmacist',                       he: 'רוקח/ת' },
  { en: 'Physiotherapist',                  he: 'פיזיותרפיסט/ית' },
  { en: 'Occupational Therapist',           he: 'מרפא/ה בעיסוק' },
  { en: 'Speech Therapist',                 he: 'קלינאי/ת תקשורת' },
  { en: 'Psychologist',                     he: 'פסיכולוג/ית' },
  { en: 'Social Worker',                    he: 'עובד/ת סוציאלי/ת' },
  { en: 'Dietitian',                        he: 'דיאטן/ית' },
  { en: 'Medical Secretary',                he: 'מזכיר/ה רפואי/ת' },
  { en: 'Caregiver',                        he: 'מטפל/ת' },
  { en: 'Lab Technician',                   he: 'לבורנט/ית' },
  { en: 'Dental Assistant',                 he: 'סייע/ת לרופא/ת שיניים' },
  // Education
  { en: 'Teacher',                          he: 'מורה' },
  { en: 'Kindergarten Teacher',             he: 'גננת / גנן' },
  { en: 'Teaching Assistant',               he: 'סייע/ת' },
  { en: 'Special Education Teacher',        he: 'מורה לחינוך מיוחד' },
  { en: 'School Counselor',                 he: 'יועץ/ת חינוכי/ת' },
  { en: 'Tutor',                            he: 'מורה פרטי/ת' },
  { en: 'Instructor',                       he: 'מדריך/ה' },
  // Engineering, industry & logistics
  { en: 'Mechanical Engineer',              he: 'מהנדס/ת מכונות' },
  { en: 'Electrical Engineer',              he: 'מהנדס/ת חשמל' },
  { en: 'Civil Engineer',                   he: 'מהנדס/ת אזרחי/ת' },
  { en: 'Industrial Engineer',              he: 'מהנדס/ת תעשייה וניהול' },
  { en: 'Architect',                        he: 'אדריכל/ית' },
  { en: 'Construction Site Manager',        he: 'מנהל/ת עבודה' },
  { en: 'Production Manager',               he: 'מנהל/ת ייצור' },
  { en: 'Quality Assurance Manager',        he: 'מנהל/ת איכות' },
  { en: 'Technician',                       he: 'טכנאי/ת' },
  { en: 'Electrician',                      he: 'חשמלאי/ת' },
  { en: 'Production Worker',                he: 'עובד/ת ייצור' },
  { en: 'Logistics Manager',                he: 'מנהל/ת לוגיסטיקה' },
  { en: 'Supply Chain Manager',             he: 'מנהל/ת שרשרת אספקה' },
  { en: 'Warehouse Worker',                 he: 'מחסנאי/ת' },
  { en: 'Driver',                           he: 'נהג/ת' },
  { en: 'Delivery Driver',                  he: 'שליח/ה' },
  { en: 'Import/Export Coordinator',        he: 'רכז/ת יבוא ויצוא' },
  // Hospitality, services & public sector
  { en: 'Chef',                             he: 'שף/ית' },
  { en: 'Cook',                             he: 'טבח/ית' },
  { en: 'Waiter',                           he: 'מלצר/ית' },
  { en: 'Restaurant Manager',               he: 'מנהל/ת מסעדה' },
  { en: 'Hotel Receptionist',               he: 'פקיד/ת קבלה במלון' },
  { en: 'Travel Agent',                     he: 'סוכן/ת נסיעות' },
  { en: 'Event Manager',                    he: 'מפיק/ת אירועים' },
  { en: 'Security Guard',                   he: 'מאבטח/ת' },
  { en: 'Cleaner',                          he: 'עובד/ת ניקיון' },
  { en: 'Hairdresser',                      he: 'ספר/ית' },
  { en: 'Beautician',                       he: 'קוסמטיקאי/ת' },
  { en: 'Fitness Trainer',                  he: 'מאמן/ת כושר' },
  { en: 'Government Affairs Manager',       he: 'מנהל/ת קשרי ממשל' },
  { en: 'Policy Advisor',                   he: 'יועץ/ת מדיניות' },
  { en: 'Community Manager',                he: 'מנהל/ת קהילה' },
  { en: 'Nonprofit Program Coordinator',    he: 'רכז/ת תוכניות בעמותה' },
  { en: 'Journalist',                       he: 'עיתונאי/ת' },
  { en: 'Translator',                       he: 'מתרגם/ת' },
  { en: 'Photographer',                     he: 'צלם/ת' },
  { en: 'Video Editor',                     he: 'עורך/ת וידאו' },
]

// "סוכן/ת ביטוח" must match "סוכן", "סוכנת" and "insurance". The search text
// holds both the masculine form (slash suffix dropped) and the feminine one
// (suffix joined, with the final letter opened: סוכן/ת → סוכנת).
const FINAL: Record<string, string> = { 'ן': 'נ', 'ם': 'מ', 'ך': 'כ', 'ף': 'פ', 'ץ': 'צ' }
const clean = (s: string) => s.toLowerCase().replace(/["'()]/g, '')
const masculine = (s: string) => clean(s).replace(/\/[\u05d0-\u05ea]{1,3}(?=[\s)]|$)/g, '')
const feminine  = (s: string) => clean(s).replace(
  /([\u05d0-\u05ea])\/([\u05d0-\u05ea]{1,3})(?=[\s)]|$)/g, (_, last: string, suf: string) => (FINAL[last] ?? last) + suf,
)
const haystack = (r: RoleOption) => `${clean(r.en)} ${masculine(r.he)} ${feminine(r.he)}`

/** Suggestions for `query`, word-prefix matches first, then substring matches. */
export function searchRoles(query: string, exclude: ReadonlySet<string>, limit = 8): RoleOption[] {
  const q = clean(query.trim())
  const pool = ROLE_CATALOG.filter(r => !exclude.has(r.en.toLowerCase()))
  if (!q) return pool.slice(0, limit)
  const starts   = pool.filter(r => haystack(r).split(/[\s/]+/).some(w => w.startsWith(q)))
  const contains = pool.filter(r => !starts.includes(r) && haystack(r).includes(q))
  return [...starts, ...contains].slice(0, limit)
}

/** The label to show for a stored role: the catalog's translation, or the role as typed. */
export function roleLabel(stored: string, lang: string): string {
  if (lang !== 'he') return stored
  return ROLE_CATALOG.find(r => r.en.toLowerCase() === stored.toLowerCase())?.he ?? stored
}
