'use client'

import { useI18n } from '@/contexts/I18nContext'
import type { HebrewForm } from '@/lib/api'

const FORMS: HebrewForm[] = ['m', 'f', 'n']

/** He / she / neutral wording for Hebrew text about the user (CV titles). */
export function HebrewFormPicker({ value, onChange, disabled = false }: {
  value:    HebrewForm | null
  onChange: (v: HebrewForm) => void
  disabled?: boolean
}) {
  const R = useI18n().t.required_details
  const label = { m: R.hebrew_m, f: R.hebrew_f, n: R.hebrew_n }
  return (
    <div className="flex flex-col sm:flex-row gap-2" role="radiogroup" aria-label={R.hebrew_heading}>
      {FORMS.map(f => {
        const on = value === f
        return (
          <button
            key={f}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => onChange(f)}
            className={`flex-1 rounded-lg border px-3 py-2.5 text-[13px] font-medium text-start transition ${
              on ? 'border-teal-500 bg-teal-50 text-teal-800' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
            }`}
          >
            {label[f]}
          </button>
        )
      })}
    </div>
  )
}
