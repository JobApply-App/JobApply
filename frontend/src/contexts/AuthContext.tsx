'use client'

/**
 * AuthContext — Supabase authentication state for the entire app.
 *
 * Provides:
 *   user          — current Supabase User (null = not signed in)
 *   session       — current Session (null = not signed in)
 *   loading       — true while the initial session check is in progress
 *   signIn        — email + password sign-in
 *   signUp        — email + password registration
 *   signInWithGoogle — Google OAuth (PKCE, redirects to /auth/callback)
 *   signOut       — wipe all storage, clear auth header, redirect to /login
 *
 * Eviction strategy (layered, most aggressive first):
 *
 *   Layer 1 — Synchronous pre-check (runs before the Supabase SDK reads storage)
 *     Scans every localStorage key for known mock emails.  If found, wipes
 *     localStorage + sessionStorage and hard-redirects via window.location.href
 *     before getSession() is ever called.  This prevents the SDK from loading
 *     the stale token into memory at all.
 *
 *   Layer 2 — Async session validation (runs after getSession() resolves)
 *     _isSuspectSession() checks the live Session object for mock emails and
 *     malformed JWT shapes.  On a hit: signOut + storage wipe + hard redirect.
 *
 *   Layer 3 — Global API error interceptor
 *     Any 401 or 503 from the backend triggers immediate signOut + storage wipe
 *     + hard redirect, regardless of which component triggered the request.
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from 'react'
import type { Session, User } from '@supabase/supabase-js'

import { supabase } from '@/lib/supabase'
import { setAuthToken, setAuthErrorHandler } from '@/lib/api'

// ── Mock-session detection ────────────────────────────────────────────────────

const MOCK_EMAILS = ['alex@example.com', 'dev@localhost']

/**
 * Returns true if a live Session object should be forcibly purged.
 * Covers:
 *   1. Known dev-fixture emails that should never appear in production.
 *   2. Access tokens that don't look like real JWTs (three dot-separated
 *      segments, first segment Base64 of '{"') — rejected by the backend
 *      anyway, but purging early prevents a flash of authenticated UI.
 */
function _isSuspectSession(s: Session): boolean {
  if (MOCK_EMAILS.includes(s.user?.email ?? '')) return true
  const parts = (s.access_token ?? '').split('.')
  if (parts.length !== 3 || !parts[0].startsWith('eyJ')) return true
  return false
}

/**
 * Synchronously scans every localStorage entry for known mock emails.
 * Called once on mount, BEFORE getSession(), so the Supabase SDK never
 * has a chance to hydrate a stale mock token into memory.
 * Returns true if a suspect entry was found (caller should wipe + redirect).
 */
function _storageContainsMockSession(): boolean {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key) continue
      const raw = localStorage.getItem(key) ?? ''
      if (MOCK_EMAILS.some(email => raw.includes(email))) return true
    }
  } catch {
    // localStorage may be unavailable in certain SSR / privacy contexts
  }
  return false
}

// ── Hard-evict helper ─────────────────────────────────────────────────────────

/**
 * Wipes all client-side storage and performs a full-page navigation to /login.
 * Using window.location.href (not router.push) ensures:
 *   - The Next.js client-side cache is completely discarded.
 *   - All React state and in-flight requests are abandoned.
 *   - The browser sends no stale cookies or prefetch hints to the next page.
 */
async function _hardEvict(): Promise<void> {
  try { await supabase?.auth.signOut() } catch { /* best-effort server signout */ }
  try { localStorage.clear()   } catch {}
  try { sessionStorage.clear() } catch {}
  // Hard navigation — breaks all Next.js client cache
  window.location.href = '/login'
}

// ── Context shape ─────────────────────────────────────────────────────────────

interface AuthContextValue {
  user:    User    | null
  session: Session | null
  loading: boolean
  signIn:                 (email: string, password: string) => Promise<void>
  signUp:                 (email: string, password: string, fullName?: string) => Promise<void>
  signInWithGoogle:       (redirectTo?: string)             => Promise<void>
  signOut:                ()                                => Promise<void>
  // ── Password reset (OTP flow) ─────────────────────────────────────────────
  sendPasswordResetOtp:   (email: string)                   => Promise<void>
  verifyPasswordResetOtp: (email: string, token: string)    => Promise<void>
  updatePassword:         (newPassword: string)             => Promise<void>
  // ── User metadata ─────────────────────────────────────────────────────────
  updateUserMeta:         (data: Record<string, unknown>)   => Promise<void>
}

const AuthContext = createContext<AuthContextValue>({
  user:    null,
  session: null,
  loading: false,
  signIn:                 async () => {},
  signUp:                 async () => {},
  signInWithGoogle:       async (_redirectTo?: string) => {},
  signOut:                async () => {},
  sendPasswordResetOtp:   async () => {},
  verifyPasswordResetOtp: async () => {},
  updatePassword:         async () => {},
  updateUserMeta:         async () => {},
})

// ── Provider ──────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user,    setUser]    = useState<User    | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  // Always start loading — AuthGuard must never render protected content before
  // the session check resolves, regardless of Supabase configuration.
  const [loading, setLoading] = useState(true)

  // Writes the resolved session to React state AND to api.ts's auth header
  // so every subsequent fetch carries the correct Bearer token.
  const _applySession = useCallback((s: Session | null) => {
    setSession(s)
    setUser(s?.user ?? null)
    setAuthToken(s?.access_token ?? null)
  }, [])

  useEffect(() => {
    // ── No Supabase client configured ───────────────────────────────────────
    // Resolve loading immediately so AuthGuard redirects to /login.
    if (!supabase) {
      setLoading(false)
      return
    }

    // ── Layer 1: synchronous storage scan ───────────────────────────────────
    // Run BEFORE getSession() so the Supabase SDK never loads a mock token.
    if (_storageContainsMockSession()) {
      // Fire-and-forget — _hardEvict navigates away, so nothing after this
      // line will execute in this page context.
      void _hardEvict()
      return
    }

    // ── Layer 3: global API error interceptor ───────────────────────────────
    // A 401 no longer evicts blindly: requests racing a token refresh (or the
    // USER_UPDATED window after updateUserMeta) can 401 while the session is
    // perfectly valid. Confirm with the Supabase SDK first — evict only when
    // the session is actually gone; otherwise refresh the auth header and let
    // the caller retry.
    const sb = supabase   // narrowed non-null reference for the async closure
    setAuthErrorHandler(() => {
      void (async () => {
        try {
          const { data } = await sb.auth.getSession()
          if (data.session) {
            setAuthToken(data.session.access_token)   // transient 401 — header was stale
            return
          }
        } catch { /* fall through to evict */ }
        await _hardEvict()
      })()
    })

    // ── Layer 2: async session validation ───────────────────────────────────
    // The Supabase SDK restores any session persisted in localStorage.
    // Validate it before accepting it.
    supabase.auth.getSession().then(async ({ data }) => {
      const s = data.session

      if (s && _isSuspectSession(s)) {
        // Hard-evict: sign out server-side, wipe storage, hard-redirect.
        await _hardEvict()
        // _hardEvict navigates away — setLoading is irrelevant, but set it
        // for correctness in the unlikely event navigation is momentarily
        // deferred (e.g. beforeunload handler).
        return
      }

      _applySession(s)
      setLoading(false)
    })

    // Keep in sync with sign-in, sign-out, and silent token-refresh events.
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, s) => {
        // Guard onAuthStateChange too: a SIGNED_IN event for a mock user
        // (e.g. from a cached refresh token) should never reach the app.
        if (s && _isSuspectSession(s)) {
          void _hardEvict()
          return
        }
        // CRITICAL: only an explicit SIGNED_OUT may null the session.
        // Supabase can emit transiently-null sessions around USER_UPDATED /
        // TOKEN_REFRESHED (e.g. while updateUser() holds the auth lock during
        // the onboarding → dashboard transition). Blindly applying that null
        // logged the user out: user became null for one render, AuthGuard's
        // effect fired router.push('/login'), and the session was dropped.
        if (!s && event !== 'SIGNED_OUT') return
        _applySession(s)
      },
    )

    return () => subscription.unsubscribe()
  }, [_applySession])

  // ── Auth actions ────────────────────────────────────────────────────────────

  const signIn = useCallback(async (email: string, password: string) => {
    if (!supabase) return
    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
    // Eagerly apply so _authToken is set before the caller navigates to the
    // dashboard and fires its first API requests.  onAuthStateChange will also
    // fire shortly after — that duplicate _applySession call is idempotent.
    if (data.session) _applySession(data.session)
  }, [_applySession])

  const signUp = useCallback(async (email: string, password: string, fullName?: string) => {
    if (!supabase) return
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        // Without this, Supabase's confirmation-email link falls back to
        // whatever "Site URL" is configured in the dashboard (a fixed value,
        // e.g. localhost:3000 left over from before this app was deployed) —
        // so confirmation emails would redirect there regardless of whether
        // the user actually signed up from local dev or the deployed site.
        // Matches the same window.location.origin pattern signInWithGoogle
        // already uses. NOTE: the target origin must also be added to
        // Supabase's Auth > URL Configuration > Redirect URLs allow-list in
        // the dashboard — Supabase ignores emailRedirectTo for any origin
        // not on that list and falls back to the Site URL regardless.
        emailRedirectTo: `${window.location.origin}/auth/callback`,
        // Persist full_name and name into user_metadata immediately so the
        // dashboard greeting and avatar initials are correct from the very
        // first session — no profile-builder step required.
        ...(fullName?.trim() ? {
          data: {
            full_name: fullName.trim(),
            name:      fullName.trim(),
          },
        } : {}),
      },
    })
    if (error) throw error
    // When email confirmation is disabled, signUp returns a session immediately.
    // When confirmation IS required, data.session is null; onAuthStateChange
    // handles the token once the user clicks the confirmation link.
    if (data.session) _applySession(data.session)
  }, [_applySession])

  // ── Password reset (OTP flow) ──────────────────────────────────────────────
  // Step 1: send 6-digit OTP to email (never creates a new account)
  const sendPasswordResetOtp = useCallback(async (email: string) => {
    if (!supabase) return
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: false },
    })
    if (error) throw error
  }, [])

  // Step 2: verify OTP → creates an active session so updatePassword works
  const verifyPasswordResetOtp = useCallback(async (email: string, token: string) => {
    if (!supabase) return
    const { data, error } = await supabase.auth.verifyOtp({
      email,
      token,
      type: 'email',
    })
    if (error) throw error
    if (data.session) _applySession(data.session)
  }, [_applySession])

  // Step 3: set the new password (requires active session from step 2)
  const updatePassword = useCallback(async (newPassword: string) => {
    if (!supabase) return
    const { error } = await supabase.auth.updateUser({ password: newPassword })
    if (error) throw error
  }, [])

  // ── User metadata update ───────────────────────────────────────────────────
  const updateUserMeta = useCallback(async (data: Record<string, unknown>) => {
    if (!supabase) return
    const { data: updated, error } = await supabase.auth.updateUser({ data })
    if (error) throw error
    // Eagerly reflect the new metadata in local state so gated UI (e.g. the
    // profile_completed check) updates in the same tick — no dependence on
    // the USER_UPDATED event timing, no flash after router.push.
    if (updated.user) setUser(updated.user)
  }, [])

  const signInWithGoogle = useCallback(async (redirectTo?: string) => {
    if (!supabase) {
      // Technical detail (exact env var names) is for whoever's running this
      // locally/in CI to see in the console — never in a message an actual
      // end user could see rendered in the sign-in form's error banner.
      console.error(
        'Authentication is not configured. ' +
        'Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in .env.local.'
      )
      throw new Error('Sign-in is temporarily unavailable. Please try again shortly.')
    }
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options:  { redirectTo: redirectTo ?? `${window.location.origin}/auth/callback` },
    })
    if (error) throw error
  }, [])

  const signOut = useCallback(async () => {
    // Use _hardEvict for consistency — full storage wipe + hard navigation
    // ensures no stale tokens or cached UI survive the sign-out.
    await _hardEvict()
  }, [])

  return (
    <AuthContext.Provider value={{
      user, session, loading,
      signIn, signUp, signInWithGoogle, signOut,
      sendPasswordResetOtp, verifyPasswordResetOtp, updatePassword,
      updateUserMeta,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  return useContext(AuthContext)
}
