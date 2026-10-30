'use client'

import { useMemo, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import type { SeniorityLevel } from '@/lib/api'
import { roleLabel, searchRoles } from '@/lib/roleCatalog'

/*
 * Target roles, each with the user's level in it. Shared by onboarding and
 * the required-details step shown at login.
 */

// Values are persisted to the profile and stay English — the stored profile
// is canonically English so downstream matching sees one spelling per level
// (see backend migration c5a91b3e7d02). Only the display labels translate,
// from onboarding.preferences.seniority, indexed against this list.
export const SENIORITY_VALUES: SeniorityLevel[] = [
  'junior', 'mid', 'senior', 'lead', 'director', 'executive',
]

// ── Roles combobox with per-role seniority ────────────────────────────────────

export interface PendingRole {
  role:      string
  seniority: SeniorityLevel | null   // null until the user picks a level
}

export function RolePicker({ selected, setSelected }: {
  selected:    PendingRole[]
  setSelected: React.Dispatch<React.SetStateAction<PendingRole[]>>
}) {
  const { t, locale } = useI18n()
  const P = t.onboarding.preferences
  const [query,     setQuery]     = useState('')
  const [open,      setOpen]      = useState(false)
  const [highlight, setHighlight] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const suggestions = useMemo(
    () => searchRoles(query, new Set(selected.map(r => r.role.toLowerCase()))),
    [query, selected],
  )
  // Anything not in the list can still be added as typed — say so, instead of
  // leaving it to an Enter key a phone keyboard may label "Go".
  const typed = query.trim()
  const offerCustom = typed.length > 1 && !suggestions.some(r =>
    [r.en, r.he].some(l => l.toLowerCase() === typed.toLowerCase()))
  const optionCount = suggestions.length + (offerCustom ? 1 : 0)
  const label = (r: { en: string; he: string }) => (locale === 'he' ? r.he : r.en)

  const addRole = (role: string) => {
    const value = role.trim()
    if (!value || selected.length >= 10) return
    if (selected.some(r => r.role.toLowerCase() === value.toLowerCase())) return
    setSelected(prev => [...prev, { role: value, seniority: null }])
    setQuery('')
    setHighlight(0)
    setOpen(false)
    inputRef.current?.focus()
  }

  return (
    <div>
      {/* Combobox input */}
      <div className="relative">
        <input
          id="target-roles-combobox"
          ref={inputRef}
          value={query}
          role="combobox"
          aria-expanded={open && optionCount > 0}
          aria-autocomplete="list"
          aria-controls="role-suggestions"
          onChange={e => { setQuery(e.target.value); setOpen(true); setHighlight(0) }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setHighlight(h => Math.min(h + 1, optionCount - 1)) }
            if (e.key === 'ArrowUp')   { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)) }
            if (e.key === 'Enter') {
              e.preventDefault()
              if (suggestions[highlight]) addRole(suggestions[highlight].en)
              else if (typed)             addRole(typed)   // free-text custom role
            }
            if (e.key === 'Escape') setOpen(false)
          }}
          placeholder={P.role_placeholder}
          maxLength={80}
          disabled={selected.length >= 10}
          className="w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-base sm:text-[13.5px] text-slate-800 placeholder:text-slate-300 outline-none focus:border-teal-400 transition disabled:opacity-50"
        />

        {open && optionCount > 0 && (
          <ul
            id="role-suggestions"
            role="listbox"
            className="absolute left-0 right-0 top-[calc(100%+4px)] z-30 rounded-xl bg-white border border-slate-100 shadow-elevation-2 overflow-hidden max-h-64 overflow-y-auto"
          >
            {suggestions.map((s, i) => (
              <li key={s.en} role="option" aria-selected={i === highlight}>
                <button
                  onMouseDown={e => { e.preventDefault(); addRole(s.en) }}
                  onMouseEnter={() => setHighlight(i)}
                  className={`w-full text-start px-3.5 py-2.5 text-[13px] transition ${
                    i === highlight ? 'bg-teal-50 text-teal-800' : 'text-slate-700'
                  }`}
                >
                  {label(s)}
                  {locale === 'he' && <span className="ms-2 text-[11.5px] text-slate-400" dir="ltr">{s.en}</span>}
                </button>
              </li>
            ))}
            {offerCustom && (
              <li role="option" aria-selected={highlight === suggestions.length}>
                <button
                  onMouseDown={e => { e.preventDefault(); addRole(typed) }}
                  onMouseEnter={() => setHighlight(suggestions.length)}
                  className={`w-full text-start px-3.5 py-2.5 text-[13px] border-t border-slate-100 transition ${
                    highlight === suggestions.length ? 'bg-teal-50 text-teal-800' : 'text-slate-600'
                  }`}
                >
                  {P.add_custom_role.replace('{role}', typed)}
                </button>
              </li>
            )}
          </ul>
        )}
      </div>

      {/* Selected roles — each with its own seniority selector */}
      {selected.length > 0 && (
        <ul className="mt-4 space-y-2.5">
          {selected.map(item => (
            <li
              key={item.role}
              className="rounded-xl border border-slate-100 bg-slate-50/60 px-3.5 py-3"
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className="text-[13.5px] font-semibold text-slate-800">{roleLabel(item.role, locale)}</span>
                <button
                  onClick={() => setSelected(prev => prev.filter(r => r.role !== item.role))}
                  aria-label={P.remove_role.replace('{role}', item.role)}
                  className="text-slate-300 hover:text-slate-600 text-[13px] transition"
                >✕</button>
              </div>
              {/* Testers didn't realise the chips were "your level in this
                  role", or how Senior differed from Lead. A labelled heading
                  and a one-line meaning for the chosen level fix both. */}
              <p className="text-[11.5px] font-semibold text-slate-600 mb-1.5">
                {P.level_heading.replace('{role}', item.role)}
              </p>
              <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={P.level_for_role.replace('{role}', item.role)}>
                {SENIORITY_VALUES.map((value, i) => {
                  const on = item.seniority === value
                  return (
                    <button
                      key={value}
                      role="radio"
                      aria-checked={on}
                      title={P.seniority_hint[i]}
                      onClick={() =>
                        setSelected(prev => prev.map(r =>
                          r.role === item.role ? { ...r, seniority: on ? null : value } : r
                        ))
                      }
                      className={`text-[11.5px] font-medium px-2.5 py-1 rounded-full border transition ${
                        on
                          ? 'border-teal-400 bg-teal-100 text-teal-800'
                          : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'
                      }`}
                    >
                      {P.seniority[i]}
                    </button>
                  )
                })}
              </div>
              <p className="mt-1.5 text-[11px] text-slate-500" aria-live="polite">
                {item.seniority === null
                  ? P.pick_level
                  : P.seniority_hint[SENIORITY_VALUES.indexOf(item.seniority)]}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
