'use client'

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
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

const LS_KEY = 'jobapply_locale'
const DEFAULT_LOCALE: Locale = 'en'

// ── Provider ───────────────────────────────────────────────────────────────────

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    // SSR guard — localStorage is unavailable during server rendering
    if (typeof window === 'undefined') return DEFAULT_LOCALE
    const stored = localStorage.getItem(LS_KEY)
    return stored === 'en' || stored === 'he' ? stored : DEFAULT_LOCALE
  })

  const dir: 'ltr' | 'rtl' = locale === 'he' ? 'rtl' : 'ltr'

  // Sync <html dir> and <html lang> with every locale change.
  // We update the DOM directly because the <html> element is owned by
  // the server-rendered layout and cannot be driven by React state alone.
  useEffect(() => {
    document.documentElement.dir  = dir
    document.documentElement.lang = locale
  }, [locale, dir])

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
    try { localStorage.setItem(LS_KEY, l) } catch { /* storage quota */ }
  }, [])

  const value: I18nContextValue = {
    locale,
    setLocale,
    t: dictionaries[locale],
    dir,
  }

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
