'use client'

/**
 * OnboardingContext — persists signup metadata (fullName, careerStage) across the
 * signup → workspace-animation → /onboarding navigation.
 *
 * Storage strategy: values live in React state (fast reads) AND sessionStorage
 * (survives a full-page reload during the redirect).  Both are kept in sync.
 *
 * Once ArielChat has consumed the greeting the context is cleared so repeat
 * visits don't re-fire the welcome message.
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface OnboardingData {
  fullName:    string
  careerStage: string
  /** Target roles + per-role seniority picked during onboarding (optional —
   *  older sessionStorage payloads won't have it). Ariel's welcome message
   *  uses this to greet the user with their actual selections. */
  roles?: { role: string; seniority: string }[]
}

interface OnboardingCtxValue {
  data:  OnboardingData | null
  set:   (d: OnboardingData) => void
  clear: () => void
}

const STORAGE_KEY = 'ja_onboarding_ctx'

// ── Context ───────────────────────────────────────────────────────────────────

const Ctx = createContext<OnboardingCtxValue | null>(null)

function readStorage(): OnboardingData | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as OnboardingData) : null
  } catch {
    return null
  }
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<OnboardingData | null>(() => readStorage())

  const set = useCallback((d: OnboardingData) => {
    setData(d)
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(d)) } catch { /* ignore */ }
  }, [])

  const clear = useCallback(() => {
    setData(null)
    try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
  }, [])

  return <Ctx.Provider value={{ data, set, clear }}>{children}</Ctx.Provider>
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useOnboarding(): OnboardingCtxValue {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useOnboarding must be used inside <OnboardingProvider>')
  return ctx
}
