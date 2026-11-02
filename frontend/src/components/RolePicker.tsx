'use client'

import { useMemo, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import type { SeniorityLevel } from '@/lib/api'
import { authInput } from '@/components/auth/authStyles'
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
          className={authInput()}
        />

        {open && optionCount > 0 && (
          <ul
            id="role-suggestions"
            role="listbox"
            className="absolute inset-x-0 top-[calc(100%+6px)] z-30 rounded-xl bg-white border border-slate-100 shadow-floating overflow-hidden max-h-64 overflow-y-auto"
          >
            {suggestions.map((s, i) => (
              <li key={s.en} role="option" aria-selected={i === highlight}>
                <button
                  onMouseDown={e => { e.preventDefault(); addRole(s.en) }}
                  onMouseEnter={() => setHighlight(i)}
                  className={`w-full text-start px-4 py-2.5 text-[15px] ${
                    i === highlight ? 'bg-teal-50 text-teal-900' : 'text-slate-700'
                  }`}
                >
                  {label(s)}
                  {locale === 'he' && <span className="ms-2 text-[13px] text-slate-500" dir="ltr">{s.en}</span>}
                </button>
              </li>
            ))}
            {offerCustom && (
              <li role="option" aria-selected={highlight === suggestions.length}>
                <button
                  onMouseDown={e => { e.preventDefault(); addRole(typed) }}
                  onMouseEnter={() => setHighlight(suggestions.length)}
                  className={`w-full text-start px-4 py-2.5 text-[15px] border-t border-slate-100 ${
                    highlight === suggestions.length ? 'bg-teal-50 text-teal-900' : 'text-slate-600'
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
        <ul className="mt-4 divide-y divide-slate-100 border-y border-slate-100">
          {selected.map(item => (
            <li
              key={item.role}
              className="py-4"
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className="text-[16px] font-semibold text-slate-900">{roleLabel(item.role, locale)}</span>
                <button
                  onClick={() => setSelected(prev => prev.filter(r => r.role !== item.role))}
                  aria-label={P.remove_role.replace('{role}', item.role)}
                  className="-me-2 flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-600"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                    <line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" />
                  </svg>
                </button>
              </div>
              {/* Testers didn't realise the chips were "your level in this
                  role", or how Senior differed from Lead. A labelled heading
                  and a one-line meaning for the chosen level fix both. */}
              <p className="text-[14px] text-slate-600 mb-2">
                {P.level_heading.replace('{role}', item.role)}
              </p>
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={P.level_for_role.replace('{role}', item.role)}>
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
                      type="button"
                      className={`min-h-10 rounded-lg border px-3 text-[14px] font-medium transition-[background-color,border-color,transform] duration-ja-ui active:scale-[0.97] active:duration-ja-press focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 ${
                        on
                          ? 'border-teal-700 bg-teal-50 text-teal-900'
                          : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      {P.seniority[i]}
                    </button>
                  )
                })}
              </div>
              <p className="mt-2 text-[14px] text-slate-500" aria-live="polite">
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
