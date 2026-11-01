'use client'

import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { LOCALES } from '@/locales'
import { CheckIcon } from '@/components/icons'

// ── LanguageSwitcher ───────────────────────────────────────────────────────────
//
// A globe button that opens a menu of the interface languages, with the
// visitor's country under them. Rendered from LOCALES, so a new language
// appears here by adding one entry there. The one language control in the app:
// every header, auth page and the mobile drawer use this component, so they
// look and behave the same (Ron, 2026-11-01).
//
// Lives in the header, not in a settings page: someone who lands in a language
// they cannot read needs to escape it from wherever they are. That is also why
// the trigger is a globe and each language is written in its own script.
//
// The country is read from the browser only (time zone, then the language's
// region), never asked for and never sent anywhere. It is shown, not chosen.

function GlobeIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18Z" />
    </svg>
  )
}

// Israel is the product's market, so its time zone is named outright; anywhere
// else falls back to the region in the browser's languages (en-GB → GB).
function detectCountry(): string | null {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    if (tz === 'Asia/Jerusalem' || tz === 'Asia/Tel_Aviv') return 'IL'
    for (const l of navigator.languages ?? [navigator.language]) {
      const region = new Intl.Locale(l).region
      if (region) return region
    }
  } catch { /* an old browser without Intl.Locale: show no country */ }
  return null
}

export function LanguageSwitcher({ className = '' }: { className?: string }) {
  const { t, locale, setLocale } = useI18n()
  const [open, setOpen] = useState(false)
  const [country, setCountry] = useState<string | null>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const items = useRef<(HTMLButtonElement | null)[]>([])

  // After mount only: the server cannot know the visitor's browser.
  useEffect(() => { setCountry(detectCountry()) }, [])

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    items.current[LOCALES.findIndex(l => l.code === locale)]?.focus()
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open, locale])

  const close = () => { setOpen(false); trigger.current?.focus() }

  const onMenuKey = (e: KeyboardEvent) => {
    const i = items.current.findIndex(el => el === document.activeElement)
    if (e.key === 'Escape') { e.preventDefault(); close() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); items.current[(i + 1) % LOCALES.length]?.focus() }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items.current[(i - 1 + LOCALES.length) % LOCALES.length]?.focus() }
    else if (e.key === 'Tab') setOpen(false)
  }

  const current = LOCALES.find(l => l.code === locale) ?? LOCALES[0]
  let countryName: string | null = null
  try { countryName = country && new Intl.DisplayNames([locale], { type: 'region' }).of(country) || null } catch { /* unknown code */ }

  return (
    <div ref={wrap} className={`relative inline-flex ${className}`}>
      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen(v => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${t.auth_layout.language}: ${current.native}`}
        className="ja-press inline-flex items-center justify-center gap-1.5 h-9 px-2.5 w-full rounded-lg text-[13px] font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600"
      >
        <GlobeIcon />
        <span lang={current.code}>{current.native}</span>
      </button>

      {open && (
        <div
          role="menu"
          aria-label={t.auth_layout.language}
          onKeyDown={onMenuKey}
          className="absolute end-0 top-full mt-2 w-56 rounded-2xl bg-white/90 backdrop-blur-xl border border-white/60 shadow-floating p-2 z-50 animate-ja-menu-in motion-reduce:animate-none origin-top-right rtl:origin-top-left"
        >
          <ul className="divide-y divide-slate-100 px-2">
            {LOCALES.map(({ code, native }, i) => (
              <li key={code}>
                <button
                  ref={el => { items.current[i] = el }}
                  type="button"
                  role="menuitemradio"
                  aria-checked={locale === code}
                  lang={code}
                  onClick={() => { setLocale(code); close() }}
                  className={`w-full flex items-center justify-between gap-3 py-2.5 text-[15px] rounded-md transition-colors outline-none focus-visible:bg-slate-100 hover:text-slate-900 ${
                    locale === code ? 'font-semibold text-slate-900' : 'text-slate-500'
                  }`}
                >
                  {native}
                  {locale === code && <span className="text-teal-700"><CheckIcon s={14} /></span>}
                </button>
              </li>
            ))}
          </ul>
          {countryName && (
            <div className="mt-2 flex items-center justify-between gap-3 rounded-xl bg-slate-100/80 px-3 py-2.5 text-[13.5px]">
              <span className="text-slate-500">{t.auth_layout.location}</span>
              <span className="font-medium text-slate-800">{countryName}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
