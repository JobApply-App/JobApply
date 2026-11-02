'use client'

import { useMemo, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { authInput } from './authStyles'
import { ComboChevron } from './ComboChevron'

export interface HomeCity { en: string; he: string; alt?: string[] }

const fold = (s: string) => s.toLowerCase().replace(/['׳’"״*]/g, '').replace(/[-־]/g, ' ').replace(/קריית/g, 'קרית')
const HEBREW = /[֐-׿]/

/**
 * The user's home locality, from the official list: it has to be a place we
 * hold coordinates for, or it could not be measured from. Search works in
 * either language whatever the interface is in, and `en` is what gets saved.
 */
export function CityPicker({ id, cities, value, onChange, disabled }: {
  id:       string
  cities:   HomeCity[]
  value:    string | null
  onChange: (city: string | null) => void
  disabled: boolean
}) {
  const { t, locale } = useI18n()
  const A = t.onboarding.about
  // null = not typing, so the field shows the chosen city.
  const [query,     setQuery]     = useState<string | null>(null)
  const [open,      setOpen]      = useState(false)
  const [highlight, setHighlight] = useState(0)
  // The language they searched in names the place from then on.
  const [lang,      setLang]      = useState<'he' | 'en' | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const typed  = (query ?? '').trim()
  const inHebrew = typed ? HEBREW.test(typed) : (lang ?? locale) === 'he'
  const label  = (c: HomeCity, he = inHebrew) => (he ? c.he : c.en)
  const chosen = cities.find(c => c.en === value)

  const q = fold(typed)
  const matches = useMemo(() => {
    if (!q) return cities
    const names = (c: HomeCity) => [c.en, c.he, ...(c.alt ?? [])].map(fold)
    const starts = cities.filter(c => names(c).some(n => n.startsWith(q)))
    const words  = cities.filter(c => !starts.includes(c) && names(c).some(n => n.includes(` ${q}`)))
    const inside = cities.filter(c => !starts.includes(c) && !words.includes(c) && names(c).some(n => n.includes(q)))
    return [...starts, ...words, ...inside]
  }, [cities, q])

  const pick = (c: HomeCity) => {
    onChange(c.en)
    setLang(inHebrew ? 'he' : 'en')
    setQuery(null)
    setOpen(false)
  }

  return (
    <div className="relative">
      <input
        ref={input}
        id={id}
        role="combobox"
        aria-expanded={open && matches.length > 0}
        aria-autocomplete="list"
        aria-controls={`${id}-list`}
        autoComplete="off"
        value={query ?? (chosen ? label(chosen, (lang ?? locale) === 'he') : '')}
        placeholder={A.home_placeholder}
        disabled={disabled}
        onChange={e => {
          setQuery(e.target.value)
          setOpen(true)
          setHighlight(0)
          if (value) onChange(null)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={e => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setHighlight(h => Math.min(h + 1, matches.length - 1)) }
          if (e.key === 'ArrowUp')   { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)) }
          if (e.key === 'Enter')     { e.preventDefault(); if (matches[highlight]) pick(matches[highlight]) }
          if (e.key === 'Escape')    setOpen(false)
        }}
        className={`${authInput()} pe-11`}
      />
      <ComboChevron open={open} label={A.home_open} disabled={disabled}
        onToggle={() => { if (!open) input.current?.focus(); setOpen(!open) }} />
      {open && matches.length > 0 && (
        <ul id={`${id}-list`} role="listbox"
          className="absolute inset-x-0 top-[calc(100%+6px)] z-30 max-h-72 overflow-y-auto rounded-xl border border-slate-100 bg-white shadow-floating">
          {matches.map((c, i) => (
            <li key={c.en} role="option" aria-selected={i === highlight}>
              <button type="button" tabIndex={-1}
                onMouseDown={e => { e.preventDefault(); pick(c) }}
                onMouseEnter={() => setHighlight(i)}
                className={`w-full flex items-baseline justify-between gap-3 px-4 py-2.5 text-start text-[15px] ${i === highlight ? 'bg-teal-50 text-teal-900' : 'text-slate-700'}`}>
                <span dir="auto">{label(c)}</span>
                {c.en !== c.he && <span dir="auto" className="shrink-0 text-[13px] text-slate-500">{label(c, !inHebrew)}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {q && cities.length > 0 && matches.length === 0 && (
        <p className="mt-2 text-[14px] text-slate-500" aria-live="polite">{A.home_none}</p>
      )}
    </div>
  )
}
