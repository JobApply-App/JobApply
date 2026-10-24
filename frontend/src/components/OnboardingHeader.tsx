'use client'

import { Logo }    from './ui/Logo'
import { useAuth } from '@/contexts/AuthContext'
import { useI18n } from '@/contexts/I18nContext'
import { LanguageSwitcher } from './LanguageSwitcher'

/**
 * Minimal header for the onboarding flow.
 *
 * Deliberately does NOT show the main app navigation (Overview, Matches, …):
 * the user has no data behind those tabs yet, and mid-onboarding navigation
 * is the main way people fell out of the flow. Logo, language, Sign Out.
 *
 * The language toggle is here because onboarding is where a new user first
 * meets the product's copy — without it, someone who arrived in the wrong
 * language had to finish onboarding before they could switch.
 */
export function OnboardingHeader() {
  const { signOut } = useAuth()
  const H = useI18n().t.header

  return (
    <header className="w-full bg-white border-b border-slate-100 sticky top-0 z-40">
      <div className="max-w-[1920px] mx-auto px-4 sm:px-12 h-[60px] flex items-center justify-between gap-3">
        <Logo />
        <div className="flex items-center gap-2 sm:gap-3">
          <LanguageSwitcher className="shrink-0" />
          <button
            onClick={() => void signOut()}
            className="min-h-[44px] sm:min-h-0 px-2 whitespace-nowrap text-[13px] font-medium text-slate-400 hover:text-slate-700 transition-colors"
          >
            {H.sign_out}
          </button>
        </div>
      </div>
    </header>
  )
}
