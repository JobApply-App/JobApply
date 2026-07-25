import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

import { AuthProvider }        from '@/contexts/AuthContext'
import { ChatProvider }        from '@/contexts/ChatContext'
import { I18nProvider }        from '@/contexts/I18nContext'
import { OnboardingProvider }  from '@/contexts/OnboardingContext'
import { ChatOverlay }         from '@/components/ChatOverlay'
import { ChatLauncher }        from '@/components/ChatLauncher'

const inter = Inter({ subsets: ['latin', 'latin-ext'] })

export const metadata: Metadata = {
  title: 'Job Apply',
  description: 'AI-powered job search automation',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // lang and dir are overridden client-side by I18nContext on every locale change.
    // 'en' / 'ltr' are the server-rendered defaults (fastest paint, no flash).
    <html lang="en" dir="ltr">
      {/* bg-ja-bg (--ja-bg token) prevents flash of warm ivory on paint */}
      <body className={`${inter.className} bg-ja-bg min-h-screen`}>
        <I18nProvider>
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
