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
import { fetchLocalePreferences, updateLocalePreferences } from '@/lib/api'

// ── Types ──────────────────────────────────────────────────────────────────────

interface I18nContextValue {
  locale:    Locale
  setLocale: (l: Locale) => void
  t:         Dict
  dir:       'ltr' | 'rtl'
  // The language generated CVs are written in — independent of the interface
  // language on purpose: reading the product in Hebrew while applying to
  // English-speaking companies in English is a normal pattern, not an edge
  // case. Null until the server preference has loaded (anonymous visitors
  // never load one), so callers can tell "not known yet" from a real value.
  cvLocale:    Locale | null
  setCvLocale: (l: Locale) => void
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

  const [cvLocale, setCvLocaleState] = useState<Locale | null>(null)

  // Pull the signed-in user's stored preferences once on mount and adopt
  // them. The cookie/localStorage copy is only a per-browser cache; the
  // server row is what makes a language choice follow someone to a new
  // device or a fresh browser instead of silently resetting to English.
  //
  // A failure here is deliberately silent: an anonymous visitor has no
  // preferences row to read, and 401 is the normal answer, not an error
  // worth putting on screen. The cookie-derived locale already in state
  // stays in effect.
  useEffect(() => {
    let cancelled = false
    fetchLocalePreferences()
      .then((prefs) => {
        if (cancelled) return
        if (prefs.cv_locale) setCvLocaleState(prefs.cv_locale)
        // Only a real stored preference may override the language already on
        // screen. A null means this account has never chosen one, in which
        // case the visitor's own selection — the reason they are reading this
        // in Hebrew — is the better answer than a server-side default.
        const stored = prefs.ui_locale
        if (stored && stored !== locale) {
          setLocaleState(stored)
          try { localStorage.setItem(LS_KEY, stored) } catch { /* storage quota */ }
          try { writeLocaleCookie(stored) } catch { /* cookies disabled */ }
        }
      })
      .catch(() => { /* anonymous visitor or offline — keep the cookie value */ })
    return () => { cancelled = true }
    // Mount-only: this adopts the stored preference once. Re-running it on
    // every locale change would race a user's in-session switch against a
    // stale server read and flip the UI back under them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
    try { localStorage.setItem(LS_KEY, l) } catch { /* storage quota */ }
    try { writeLocaleCookie(l) } catch { /* cookies disabled */ }
    // Local state is updated first and never rolled back on failure: the
    // switch the user just made should take effect even when the write
    // fails (offline, signed out). The cookie still carries it across
    // reloads in that case.
    updateLocalePreferences({ ui_locale: l }).catch(() => { /* see above */ })
  }, [])

  const setCvLocale = useCallback((l: Locale) => {
    setCvLocaleState(l)
    updateLocalePreferences({ cv_locale: l }).catch(() => { /* see setLocale */ })
  }, [])

  // This is the outermost provider in the app (wraps everything else) — an
  // unmemoized value here would re-render the entire app on every render of
  // I18nProvider, not just on an actual locale change.
  const value: I18nContextValue = useMemo(() => ({
    locale,
    setLocale,
    t: dictionaries[locale],
    dir,
    cvLocale,
    setCvLocale,
  }), [locale, setLocale, dir, cvLocale, setCvLocale])

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
