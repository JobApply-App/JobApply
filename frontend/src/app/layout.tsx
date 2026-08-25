import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { cookies } from 'next/headers'
import './globals.css'

import { AuthProvider }        from '@/contexts/AuthContext'
import { ChatProvider }        from '@/contexts/ChatContext'
import { I18nProvider }        from '@/contexts/I18nContext'
import { OnboardingProvider }  from '@/contexts/OnboardingContext'
import { ChatOverlay }         from '@/components/ChatOverlay'
import { ChatLauncher }        from '@/components/ChatLauncher'
import type { Locale }         from '@/locales'

const inter = Inter({ subsets: ['latin', 'latin-ext'] })

export const metadata: Metadata = {
  title: {
    template: '%s | JobApply',
    default: 'JobApply',
  },
  description: 'AI-powered job search automation',
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Read the visitor's saved language choice from the cookie I18nContext
  // writes on every setLocale() call, so a returning Hebrew visitor gets
  // <html lang="he" dir="rtl"> in the very first byte the server sends,
  // instead of always starting at en/ltr and flipping client-side after
  // hydration (the flash a screen-reader user would otherwise hit). A
  // first-ever visit has no cookie yet and falls back to en/ltr, same as
  // before — there's no reliable signal to do better than that up front.
  const cookieStore   = await cookies()
  const cookieLocale  = cookieStore.get('jobapply_locale')?.value
  const locale: Locale = cookieLocale === 'he' ? 'he' : 'en'
  const dir            = locale === 'he' ? 'rtl' : 'ltr'

  return (
    <html lang={locale} dir={dir}>
      {/* bg-ja-bg (--ja-bg token) prevents flash of warm ivory on paint */}
      <body className={`${inter.className} bg-ja-bg min-h-screen`}>
        <I18nProvider initialLocale={locale}>
          <AuthProvider>
            <OnboardingProvider>
              <ChatProvider>
                {children}
                <ChatOverlay />
                <ChatLauncher />
              </ChatProvider>
            </OnboardingProvider>
          </AuthProvider>
        </I18nProvider>
      </body>
    </html>
  )
}
