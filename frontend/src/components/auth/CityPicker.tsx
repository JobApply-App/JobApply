'use client'

import { useMemo, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import type { HomeCity } from '@/lib/api'
import { authInput } from './authStyles'

const fold = (s: string) => s.toLowerCase().replace(/['׳]/g, '')

/**
 * The user's home city, from a fixed list: a city has to be one we hold
 * coordinates for, or it could not be measured from. Nearby villages pick the
 * closest city, and the hint under the field says so when a search finds none.
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
  const label = (c: HomeCity) => (locale === 'he' ? c.he : c.en)
  // null = not typing, so the field shows the chosen city.
  const [query,     setQuery]     = useState<string | null>(null)
  const [open,      setOpen]      = useState(false)
  const [highlight, setHighlight] = useState(0)

  const chosen = cities.find(c => c.en === value)
  const q = fold((query ?? '').trim())
  const matches = useMemo(() => {
    const hit = cities.filter(c => !q || fold(c.en).includes(q) || fold(c.he).includes(q))
    const starts = (c: HomeCity) => fold(c.en).startsWith(q) || fold(c.he).startsWith(q)
    return [...hit.filter(starts), ...hit.filter(c => !starts(c))].slice(0, 8)
  }, [cities, q])

  const pick = (c: HomeCity) => {
    onChange(c.en)
    setQuery(null)
    setOpen(false)
  }

  return (
    <div className="relative">
      <input
        id={id}
        role="combobox"
        aria-expanded={open && matches.length > 0}
        aria-autocomplete="list"
        aria-controls={`${id}-list`}
        autoComplete="off"
        value={query ?? (chosen ? label(chosen) : '')}
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
          if (e.key === 'ArrowDown') { e.preventDefault(); setHighlight(h => Math.min(h + 1, matches.length - 1)) }
          if (e.key === 'ArrowUp')   { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)) }
          if (e.key === 'Enter')     { e.preventDefault(); if (matches[highlight]) pick(matches[highlight]) }
          if (e.key === 'Escape')    setOpen(false)
        }}
        className={authInput()}
      />
      {open && matches.length > 0 && (
        <ul id={`${id}-list`} role="listbox"
          className="absolute inset-x-0 top-[calc(100%+6px)] z-30 max-h-64 overflow-y-auto rounded-xl border border-slate-100 bg-white shadow-floating">
          {matches.map((c, i) => (
            <li key={c.en} role="option" aria-selected={i === highlight}>
              <button type="button" tabIndex={-1}
                onMouseDown={e => { e.preventDefault(); pick(c) }}
                onMouseEnter={() => setHighlight(i)}
                className={`w-full px-4 py-2.5 text-start text-[15px] ${i === highlight ? 'bg-teal-50 text-teal-900' : 'text-slate-700'}`}>
                {label(c)}
              </button>
            </li>
          ))}
        </ul>
      )}
      {q && matches.length === 0 && (
        <p className="mt-2 text-[14px] text-slate-500" aria-live="polite">{A.home_none}</p>
      )}
    </div>
  )
}
