'use client'

import { useI18n } from '@/contexts/I18nContext'
import type { Locale } from '@/locales'

// The two settings are presented together but never as one control: reading
// the product in Hebrew while sending English CVs to English-speaking
// companies is a normal pattern here, and a single "language" toggle would
// make it unreachable. Keeping them adjacent is what makes the distinction
// legible — the second row's help text explains why it is separate.

const LOCALE_LABELS: Record<Locale, { name: string; native: string }> = {
  en: { name: 'English', native: 'English' },
  he: { name: 'Hebrew',  native: 'עברית'  },
}

const LOCALES: Locale[] = ['en', 'he']

function LocaleChoice({
  value,
  onChange,
  name,
  describedBy,
}: {
  value:       Locale
  onChange:    (l: Locale) => void
  name:        string
  describedBy: string
}) {
  return (
    <div role="radiogroup" aria-describedby={describedBy} className="flex gap-2">
      {LOCALES.map((loc) => {
        const selected = value === loc
        return (
          <button
            key={loc}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(loc)}
            className={[
              'rounded-lg px-4 py-2 text-sm font-medium transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ja-primary focus-visible:ring-offset-2',
              selected
                ? 'bg-ja-primarySubtle text-ja-primary border border-ja-primary'
                : 'bg-ja-surface text-ja-ink2 border border-ja-line hover:bg-ja-surfaceHover',
            ].join(' ')}
          >
            {/* Each option is labelled in its own language — a Hebrew speaker
                looking for Hebrew should not have to read the word "Hebrew"
                in English to find it. */}
            <span lang={loc}>{LOCALE_LABELS[loc].native}</span>
          </button>
        )
      })}
    </div>
  )
}

export function LanguageSettings() {
  const { locale, setLocale, cvLocale, setCvLocale, t } = useI18n()
  const copy = t.settings.language

  return (
    <section className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold text-ja-ink">{copy.heading}</h2>
        <p className="text-sm text-ja-muted max-w-prose">{copy.intro}</p>
      </div>

      <div className="flex flex-col gap-3">
        <label className="text-sm font-medium text-ja-ink" id="ui-locale-label">
          {copy.interface_label}
        </label>
        <p id="ui-locale-help" className="text-sm text-ja-muted max-w-prose">
          {copy.interface_help}
        </p>
        <LocaleChoice
          value={locale}
          onChange={setLocale}
          name="ui_locale"
          describedBy="ui-locale-help"
        />
      </div>

      <div className="flex flex-col gap-3">
        <label className="text-sm font-medium text-ja-ink" id="cv-locale-label">
          {copy.cv_label}
        </label>
        <p id="cv-locale-help" className="text-sm text-ja-muted max-w-prose">
          {copy.cv_help}
        </p>
        {/* cvLocale is null until the stored preference loads. Rendering the
            control against a guessed value would show a selection the user
            never made and, worse, let them "confirm" it by clicking the
            other option — so show the row as pending instead. */}
        {cvLocale === null ? (
          <p className="text-sm text-ja-subtle" aria-live="polite">{copy.loading}</p>
        ) : (
          <LocaleChoice
            value={cvLocale}
            onChange={setCvLocale}
            name="cv_locale"
            describedBy="cv-locale-help"
          />
        )}
      </div>
    </section>
  )
}
