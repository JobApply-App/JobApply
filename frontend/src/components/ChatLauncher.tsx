'use client'

import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useChat } from '@/contexts/ChatContext'
import { useAuth } from '@/contexts/AuthContext'
import { useI18n } from '@/contexts/I18nContext'
import { TOKENS }  from '@/lib/tokens'

const ONBOARDING_ROUTES = ['/onboarding', '/profile-builder']

// Strict check against BOTH the React pathname and the live browser URL —
// during soft-routing transitions they can disagree for a frame, which let
// the launcher flash mid-onboarding. Hidden if either says onboarding.
function isOnOnboardingRoute(reactPathname: string | null): boolean {
  const browserPathname = typeof window !== 'undefined' ? window.location.pathname : ''
  return ONBOARDING_ROUTES.some(r =>
    (reactPathname ?? '').startsWith(r) || browserPathname.startsWith(r)
  )
}

function ChatIcon() {
  return (
    <svg width={18} height={18} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}

// One-time introduction. Testers saw a chat button and never learned what
// Ariel is for; the bubble says it once, then gets out of the way for good.
const INTRO_SEEN_KEY = 'ja.ariel_intro_seen'

function readIntroSeen(): boolean {
  try { return window.localStorage.getItem(INTRO_SEEN_KEY) === '1' } catch { return true }
}
function markIntroSeen(): void {
  try { window.localStorage.setItem(INTRO_SEEN_KEY, '1') } catch { /* private mode — show again next time */ }
}

// Floating launcher for Ariel (authenticated career agent).
// Hidden when the panel is already open, or when the user is not signed in.
export function ChatLauncher() {
  const A = useI18n().t.ariel
  const { isOpen, isEliyaOpen, jobContext, openChat } = useChat()
  const { user } = useAuth()
  const pathname = usePathname()
  // Starts hidden and is decided after mount: localStorage is not readable
  // during server render, and showing it first would flash for returning users.
  const [showIntro, setShowIntro] = useState(false)
  useEffect(() => {
    if (readIntroSeen()) return
    const id = setTimeout(() => setShowIntro(true), 1500)
    return () => clearTimeout(id)
  }, [])
  const dismissIntro = () => { markIntroSeen(); setShowIntro(false) }

  // Ariel is available to every signed-in user outside onboarding — the same
  // rule as ChatOverlay. Gating on the wizard's profile_completed flag hid her
  // from anyone who uploaded a CV elsewhere or skipped the wizard.
  const onOnboardingRoute = isOnOnboardingRoute(pathname)

  // Hide while signed out, during onboarding, or while a chat panel is open
  if (!user || onOnboardingRoute || isOpen || isEliyaOpen) return null

  const hasContext = Boolean(jobContext)

  return (
    <>
    {showIntro && (
      <div
        role="dialog"
        aria-label={A.name}
        className="ja-launcher-intro fixed z-50 end-4 sm:end-6 bottom-[5.5rem] w-[min(18rem,calc(100vw-2rem))] rounded-2xl bg-white border border-slate-100 p-4 text-start"
        style={{ boxShadow: '0 10px 30px rgba(15,23,42,0.14), 0 2px 6px rgba(15,23,42,0.06)' }}
      >
        <p className="text-[13px] text-slate-700 leading-relaxed">{A.intro}</p>
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={() => { dismissIntro(); openChat() }}
            className="h-10 sm:h-8 px-3.5 rounded-lg text-[12.5px] font-semibold text-white"
            style={{ background: TOKENS.color.primary }}
          >
            {A.intro_open}
          </button>
          <button
            onClick={dismissIntro}
            className="h-10 sm:h-8 px-3 rounded-lg text-[12.5px] font-medium text-slate-500 hover:bg-slate-50"
          >
            {A.intro_dismiss}
          </button>
        </div>
      </div>
    )}
    <button
      onClick={() => { if (showIntro) dismissIntro(); openChat() }}
      title={A.launcher_title}
      aria-label={A.launcher_label}
      className="ja-launcher fixed bottom-6 end-4 sm:end-6 z-50 flex items-center justify-center gap-2.5 h-14 w-14 sm:h-12 sm:w-auto sm:px-4 rounded-full text-white transition-[transform,opacity] duration-200 active:scale-95 hover:opacity-90"
      style={{
        background: TOKENS.color.primary,
        boxShadow:  '0 4px 20px rgba(13,148,136,0.40)',
      }}
    >
      {/* Context dot — visible when a job topic is loaded */}
      {hasContext && (
        <span
          className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full border-2 border-white"
          style={{ background: '#f59e0b' }}
          title={A.job_context}
        />
      )}
      <span className="flex-shrink-0"><ChatIcon /></span>
      {/* Icon-only on phones: the labelled pill covered the start of every
          line of text it floated over. aria-label carries the name. */}
      <span className="hidden sm:flex flex-col items-start leading-tight">
        <span className="text-[13px] font-semibold tracking-tight">{A.name}</span>
        <span className="text-[10.5px] font-medium opacity-85">{A.launcher_sub}</span>
      </span>
    </button>
    </>
  )
}
