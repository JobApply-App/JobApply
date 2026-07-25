'use client'

import { Logo }    from './ui/Logo'
import { useAuth } from '@/contexts/AuthContext'

/**
 * Minimal header for the onboarding flow.
 *
 * Deliberately does NOT show the main app navigation (Overview, Matches, …):
 * the user has no data behind those tabs yet, and mid-onboarding navigation
 * is the main way people fell out of the flow. Logo + Sign Out only.
 */
export function OnboardingHeader() {
  const { signOut } = useAuth()

  return (
    <header className="w-full bg-white border-b border-slate-100 sticky top-0 z-40">
      <div className="max-w-[1920px] mx-auto px-6 sm:px-12 h-[60px] flex items-center justify-between">
        <Logo />
        <button
          onClick={() => void signOut()}
          className="text-[13px] font-medium text-slate-400 hover:text-slate-700 transition-colors"
        >
          Sign out
        </button>
      </div>
    </header>
  )
}
