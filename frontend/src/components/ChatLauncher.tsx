'use client'

import { usePathname } from 'next/navigation'
import { useChat } from '@/contexts/ChatContext'
import { useAuth } from '@/contexts/AuthContext'
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

// Floating launcher for Ariel (authenticated career agent).
// Hidden when the panel is already open, or when the user is not signed in.
export function ChatLauncher() {
  const { isOpen, isEliyaOpen, jobContext, openChat } = useChat()
  const { user } = useAuth()
  const pathname = usePathname()

  // Ariel only exists for completed profiles, and never during onboarding.
  const profileCompleted =
    (user?.user_metadata as Record<string, unknown> | undefined)?.profile_completed === true
  const onOnboardingRoute = isOnOnboardingRoute(pathname)

  // Only show for authenticated, onboarded users; hide if any chat panel is open
  if (!user || !profileCompleted || onOnboardingRoute || isOpen || isEliyaOpen) return null

  const hasContext = Boolean(jobContext)

  return (
    <button
      onClick={() => openChat()}
      title="Open Ariel — your career agent"
      aria-label="Open Ariel career agent"
      className="fixed bottom-6 right-6 z-50 flex items-center gap-2.5 h-12 px-4 rounded-full text-white transition-all duration-200 active:scale-95 hover:opacity-90"
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
          title="Job context loaded"
        />
      )}
      <span className="flex-shrink-0"><ChatIcon /></span>
      <span className="text-[13px] font-semibold tracking-tight">Ask Ariel</span>
    </button>
  )
}
