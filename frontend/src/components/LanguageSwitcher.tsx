'use client'

import { useI18n } from '@/contexts/I18nContext'

// ── LanguageSwitcher ───────────────────────────────────────────────────────────
//
// Renders a minimal "EN / עב" pill that toggles between locales.
// Adheres strictly to the enterprise design system:
//   • White background, border-slate-200, text-slate-500
//   • Active locale uses text-slate-900 (ink) — no heavy accent colour
//   • No shadows, no rounded-full, no ring-* utilities

export function LanguageSwitcher() {
  const { locale, setLocale } = useI18n()

  return (
    <div
      className="inline-flex items-center rounded-lg border border-slate-200 bg-white overflow-hidden"
      role="group"
      aria-label="Language selector"
    >
      {(
        [
          { value: 'en', label: 'EN'  },
          { value: 'he', label: 'עב' },
        ] as const
      ).map(({ value, label }, i) => (
        <button
          key={value}
          onClick={() => setLocale(value)}
          aria-pressed={locale === value}
          className={[
            'h-8 px-3 text-[12px] font-semibold transition-colors',
            i === 0 ? 'border-r border-slate-200' : '',
            locale === value
              ? 'text-slate-900 bg-slate-50'
              : 'text-slate-400 hover:text-slate-600 bg-white',
          ].join(' ')}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
