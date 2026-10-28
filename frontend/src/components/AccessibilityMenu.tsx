'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { useDialogA11y } from '@/hooks/useDialogA11y'
import { applyA11y, DEFAULT_A11Y, loadA11y, saveA11y, type A11ySettings, type FontSize } from '@/lib/a11yPrefs'

// ── Accessibility menu ───────────────────────────────────────────────────────
//
// A floating button on every page (desktop and mobile) that opens a panel of
// display adjustments and links to the accessibility statement. Before this
// the statement was linked only from the marketing Footer, so a signed-in
// user could not reach it at all.
//
// Built in-house rather than as a third-party overlay script: no extra cost,
// no external code reading every page, and it adjusts our own markup. The
// site itself still has to be accessible (WCAG 2.1 AA / IS 5568 — see
// /accessibility); this panel adds viewer preferences on top, it does not
// replace that work.
//
// Preference logic and storage: lib/a11yPrefs.ts.

function AccessibilityIcon({ s = 26 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="11" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="6.6" r="1.6" fill="currentColor" />
      <path d="M6.5 9.3c1.8.6 3.6.9 5.5.9s3.7-.3 5.5-.9M12 10.2v3.6m0 0-2.3 5m2.3-5 2.3 5"
        stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function AccessibilityMenu() {
  const M = useI18n().t.a11y_menu
  const [open, setOpen]         = useState(false)
  const [settings, setSettings] = useState<A11ySettings>(DEFAULT_A11Y)
  const panelRef = useRef<HTMLDivElement>(null)
  const close = useCallback(() => setOpen(false), [])
  useDialogA11y(close, panelRef, open)

  // Restore saved preferences on first load of any page.
  useEffect(() => {
    const saved = loadA11y()
    setSettings(saved)
    applyA11y(saved)
  }, [])

  const update = (patch: Partial<A11ySettings>) => {
    setSettings(prev => {
      const next = { ...prev, ...patch }
      applyA11y(next)
      saveA11y(next)
      return next
    })
  }

  const toggles: { key: keyof Omit<A11ySettings, 'font'>; label: string }[] = [
    { key: 'contrast',       label: M.contrast },
    { key: 'grayscale',      label: M.grayscale },
    { key: 'noAnimation',    label: M.no_animation },
    { key: 'highlightLinks', label: M.highlight_links },
    { key: 'readableFont',   label: M.readable_font },
    { key: 'focusRing',      label: M.focus_ring },
  ]
  const fonts: { key: FontSize; label: string }[] = [
    { key: 'small', label: M.font_small }, { key: 'medium', label: M.font_medium }, { key: 'large', label: M.font_large },
  ]

  const tile = (pressed: boolean) =>
    `min-h-[44px] rounded-xl border px-3 py-2.5 text-[13px] font-semibold text-center transition-colors ${
      pressed ? 'border-teal-700 bg-teal-50 text-teal-900' : 'border-slate-200 bg-white text-slate-800 hover:border-slate-300'
    }`

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-label={M.open}
        aria-expanded={open}
        aria-controls="a11y-menu-panel"
        className="a11y-launcher fixed bottom-6 start-4 sm:start-6 z-30 h-12 w-12 rounded-full bg-slate-900 text-white flex items-center justify-center print:hidden hover:bg-slate-800 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-teal-500"
        style={{ boxShadow: '0 1px 2px rgba(15,23,42,.12), 0 6px 18px rgba(15,23,42,.18)' }}
      >
        <AccessibilityIcon />
      </button>

      {open && (
        <div
          ref={panelRef}
          id="a11y-menu-panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby="a11y-menu-title"
          tabIndex={-1}
          className="a11y-panel fixed z-40 bottom-[5.5rem] start-4 sm:start-6 w-[min(21rem,calc(100vw-2rem))] max-h-[calc(100vh-7rem)] overflow-y-auto rounded-2xl bg-white border border-slate-200 p-4 print:hidden"
          style={{ boxShadow: '0 1px 2px rgba(15,23,42,.08), 0 12px 32px rgba(15,23,42,.18)' }}
        >
          <div className="flex items-center justify-between mb-3">
            <h2 id="a11y-menu-title" className="text-[16px] font-bold text-slate-900">{M.title}</h2>
            <button
              type="button"
              onClick={close}
              aria-label={M.close}
              className="h-11 w-11 -me-2 rounded-lg flex items-center justify-center text-slate-600 hover:bg-slate-100"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          <div role="group" aria-label={M.font_size} className="grid grid-cols-3 gap-2 mb-2">
            {fonts.map(f => (
              <button key={f.key} type="button" aria-pressed={settings.font === f.key}
                onClick={() => update({ font: f.key })} className={tile(settings.font === f.key)}>
                {f.label}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-2">
            {toggles.map(t => (
              <button key={t.key} type="button" aria-pressed={settings[t.key]}
                onClick={() => update({ [t.key]: !settings[t.key] } as Partial<A11ySettings>)}
                className={tile(settings[t.key])}>
                {t.label}
              </button>
            ))}
          </div>

          <button type="button" onClick={() => update(DEFAULT_A11Y)}
            className="mt-2 w-full min-h-[44px] rounded-xl border border-slate-200 text-[13px] font-semibold text-slate-700 hover:bg-slate-50">
            {M.reset}
          </button>

          <a href="/accessibility"
            className="mt-3 flex items-center justify-between min-h-[44px] rounded-xl border-2 border-teal-700 px-4 text-[14px] font-bold text-teal-900 hover:bg-teal-50">
            {M.statement}
            <span aria-hidden="true" className="inline-block rtl:rotate-180">›</span>
          </a>
          <p className="mt-2 text-[12px] text-slate-600">{M.active_hint}</p>
        </div>
      )}
    </>
  )
}
