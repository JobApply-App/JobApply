'use client'

import { useI18n } from '@/contexts/I18nContext'
import { LOCALES } from '@/locales'

// ── LanguageSwitcher ───────────────────────────────────────────────────────────
//
// Compact segmented pill for the interface language, rendered from LOCALES so
// a new language appears here by adding one entry there.
//
// Lives in the app header, not in a settings page: someone who lands in a
// language they cannot read needs to escape it from wherever they are, and a
// control reachable only by navigating a menu written in that language is not
// an escape. It is also the reason each button is labelled in its own script.
//
// Design system: white ground, border-slate-200, active in ink rather than an
// accent; no shadows, no rounded-full.

export function LanguageSwitcher({ className = '' }: { className?: string }) {
  const { locale, setLocale } = useI18n()

  return (
    <div
      className={`inline-flex items-center rounded-lg border border-slate-200 bg-white overflow-hidden ${className}`}
      role="group"
      aria-label="Language"
    >
      {LOCALES.map(({ code, short, native }, i) => (
        <button
          key={code}
          type="button"
          onClick={() => setLocale(code)}
          aria-pressed={locale === code}
          aria-label={native}
          title={native}
          lang={code}
          className={[
            'h-8 px-3 text-[12px] font-semibold transition-colors',
            i > 0 ? 'border-s border-slate-200' : '',
            locale === code
              ? 'text-slate-900 bg-slate-50'
              : 'text-slate-400 hover:text-slate-600 bg-white',
          ].join(' ')}
        >
          {short}
        </button>
      ))}
    </div>
  )
}
