import { cookies } from 'next/headers'

// Tab titles in the visitor's language. They were fixed English strings in
// each route's metadata, so a Hebrew page announced itself to screen readers
// (and showed in the browser tab) as "Sign In | JobApply". Read from the same
// cookie the root layout uses for <html lang/dir>, so the right title is in
// the first byte the server sends.

const TITLES = {
  en: {
    accessibility: 'Accessibility Statement', analytics: 'Analytics', signing_in: 'Signing In',
    complete_profile: 'Complete Your Profile', capabilities: 'Capabilities', discover: 'Discover Jobs',
    login: 'Sign In', onboarding: 'Get Started', profile_builder: 'Build Your Profile', signup: 'Sign Up',
    terms: 'Terms of Service', privacy: 'Privacy Policy',
  },
  he: {
    accessibility: 'הצהרת נגישות', analytics: 'אנליטיקס', signing_in: 'מתחברים…',
    complete_profile: 'השלמת הפרופיל', capabilities: 'יכולות', discover: 'משרות חדשות',
    login: 'התחברות', onboarding: 'בואו נתחיל', profile_builder: 'בניית הפרופיל', signup: 'הרשמה',
    terms: 'תנאי שימוש', privacy: 'מדיניות פרטיות',
  },
} as const

export type PageTitleKey = keyof typeof TITLES['en']

export async function pageTitle(key: PageTitleKey): Promise<string> {
  const locale = (await cookies()).get('jobapply_locale')?.value === 'he' ? 'he' : 'en'
  return TITLES[locale][key]
}
