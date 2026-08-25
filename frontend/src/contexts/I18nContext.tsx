'use client'

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react'
import { dictionaries, type Dict, type Locale } from '@/locales'

// ── Types ──────────────────────────────────────────────────────────────────────

interface I18nContextValue {
  locale:    Locale
  setLocale: (l: Locale) => void
  t:         Dict
  dir:       'ltr' | 'rtl'
}

// ── Context ────────────────────────────────────────────────────────────────────

const I18nContext = createContext<I18nContextValue | null>(null)

const LS_KEY     = 'jobapply_locale'
const COOKIE_KEY = 'jobapply_locale'
const DEFAULT_LOCALE: Locale = 'en'

// One year — a returning visitor's language choice should stick indefinitely,
// same lifetime the localStorage copy already effectively has.
const COOKIE_MAX_AGE_S = 60 * 60 * 24 * 365

function writeLocaleCookie(l: Locale) {
  // Readable by the root layout's Server Component on the next request via
  // next/headers's cookies() — this is what lets <html lang/dir> render
  // correctly on the FIRST byte instead of flashing en/ltr and flipping
  // client-side. path=/ so it's sent on every route, not just the one that
  // set it.
  document.cookie = `${COOKIE_KEY}=${l}; path=/; max-age=${COOKIE_MAX_AGE_S}; samesite=lax`
}

// ── Provider ───────────────────────────────────────────────────────────────────
//
// initialLocale comes from the root layout's server-side cookie read
// (backend/../layout.tsx -> cookies().get('jobapply_locale')). Passing it in
// means the client's very first render already matches what the server sent
// in <html lang/dir> — no flash, no hydration mismatch — for any visitor who
// has been here before. A first-ever visit (no cookie yet) still starts at
// DEFAULT_LOCALE, which is unavoidable without guessing from Accept-Language.
export function I18nProvider({
  children,
  initialLocale,
}: {
  children: ReactNode
  initialLocale?: Locale
}) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    if (initialLocale === 'en' || initialLocale === 'he') return initialLocale
    // SSR guard — localStorage is unavailable during server rendering. Only
    // reached when there was no cookie for the server to read yet.
    if (typeof window === 'undefined') return DEFAULT_LOCALE
    const stored = localStorage.getItem(LS_KEY)
    return stored === 'en' || stored === 'he' ? stored : DEFAULT_LOCALE
  })

  const dir: 'ltr' | 'rtl' = locale === 'he' ? 'rtl' : 'ltr'

  // Sync <html dir> and <html lang> with every locale change. Needed even
  // though the server now renders the correct value on first paint: this is
  // what applies a change the user makes DURING the session, since the
  // server-rendered <html> tag isn't re-rendered on a client-side locale
  // switch.
  useEffect(() => {
    document.documentElement.dir  = dir
    document.documentElement.lang = locale
  }, [locale, dir])

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
    try { localStorage.setItem(LS_KEY, l) } catch { /* storage quota */ }
    try { writeLocaleCookie(l) } catch { /* cookies disabled */ }
  }, [])

  // This is the outermost provider in the app (wraps everything else) — an
  // unmemoized value here would re-render the entire app on every render of
  // I18nProvider, not just on an actual locale change.
  const value: I18nContextValue = useMemo(() => ({
    locale,
    setLocale,
    t: dictionaries[locale],
    dir,
  }), [locale, setLocale, dir])

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  )
}

// ── Hook ───────────────────────────────────────────────────────────────────────

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used inside <I18nProvider>')
  return ctx
}
