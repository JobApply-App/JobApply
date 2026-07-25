'use client'

/**
 * /auth/callback
 *
 * Handles two distinct Supabase post-auth flows:
 *
 *   1. Email confirmation / magic link  — Supabase redirects with a hash
 *      fragment:  #access_token=...&type=signup
 *      The Supabase JS SDK auto-processes this hash on import when
 *      detectSessionInUrl=true (the default).  We yield one event-loop tick
 *      then call getSession() to read the finalised session.
 *
 *   2. Google OAuth (PKCE)  — Supabase redirects with a query param:
 *      ?code=...
 *      We explicitly call exchangeCodeForSession(code) to complete the flow.
 *
 * Loading state is always shown — a blank page is never rendered.
 */

import { useEffect, useState } from 'react'
import { useRouter }           from 'next/navigation'
import { supabase }            from '@/lib/supabase'

const LOG = '[JobApply-Auth-Callback]'

type Status = 'loading' | 'error'

export default function AuthCallbackPage() {
  const router           = useRouter()
  const [status, setStatus] = useState<Status>('loading')
  const [errMsg, setErrMsg] = useState('')

  useEffect(() => {
    if (!supabase) {
      console.error(`${LOG} Supabase client not configured`)
      router.replace('/login?error=config')
      return
    }

    async function handleCallback() {
      // Read URL fragments and params — only available client-side
      const hash   = window.location.hash   // e.g. "#access_token=...&type=signup"
      const search = window.location.search // e.g. "?code=..."
      const params = new URLSearchParams(search)
      const code   = params.get('code')

      console.log(`${LOG} hash present: ${hash.length > 1}`, `| code present: ${!!code}`)

      try {
        if (code) {
          // ── PKCE flow (Google OAuth) ──────────────────────────────────────
          console.log(`${LOG} exchanging PKCE code for session`)
          const { error } = await supabase!.auth.exchangeCodeForSession(code)
          if (error) throw error
          console.log(`${LOG} PKCE exchange success`)
        } else if (hash.includes('access_token')) {
          // ── Implicit hash flow (email confirmation / magic link) ──────────
          // The SDK processes the hash automatically on import; yield one tick
          // so it can finalise before we call getSession().
          console.log(`${LOG} hash flow detected — yielding one tick for SDK processing`)
          await new Promise(r => setTimeout(r, 0))
        } else {
          // No recognisable auth payload — treat as a direct navigation
          console.warn(`${LOG} no code or access_token found in URL`)
          router.replace('/login')
          return
        }

        // Read the finalised session (works for both flows)
        const { data, error: sessionError } = await supabase!.auth.getSession()
        if (sessionError) throw sessionError

        const session = data?.session
        if (!session?.user) {
          throw new Error('Session could not be established after exchange.')
        }

        console.log(`${LOG} session established for: ${session.user.email}`)

        // Routing decision: new Google users lack career_stage in metadata
        const meta        = session.user.user_metadata as Record<string, unknown> | null
        const careerStage = meta?.career_stage

        const destination = code && !careerStage ? '/auth/complete-profile' : '/discover'
        console.log(`${LOG} redirecting to ${destination}`)
        router.replace(destination)

      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Unknown error'
        console.error(`${LOG} session exchange failed:`, msg)
        setErrMsg(msg)
        setStatus('error')
        // Give the user 2 s to read the inline message, then redirect to login
        setTimeout(() => {
          router.replace('/login?error=link_expired')
        }, 2000)
      }
    }

    void handleCallback()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Loading ────────────────────────────────────────────────────────────────
  if (status === 'loading') {
    return (
      <div
        className="min-h-screen flex flex-col items-center justify-center gap-5 bg-ja-ink"
      >
        <div className="w-10 h-10 rounded-full border-[3px] border-slate-700 border-t-teal-400 animate-spin" />
        <p className="text-[15px] font-medium text-ja-subtle">
          Verifying your account…
        </p>
      </div>
    )
  }

  // ── Error (shown briefly before redirect to /login) ────────────────────────
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center gap-4 px-6 bg-ja-ink"
    >
      <div
        className="w-12 h-12 rounded-full flex items-center justify-center bg-red-500/15 text-red-500"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <div className="text-center space-y-1">
        <p className="text-white font-semibold">Link invalid or expired</p>
        <p className="text-sm text-ja-subtle">
          {errMsg || 'Please request a new confirmation email.'}
        </p>
      </div>
      <p className="text-xs text-ja-subtle">Redirecting to login…</p>
    </div>
  )
}
