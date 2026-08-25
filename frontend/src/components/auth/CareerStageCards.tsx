'use client'

import { useI18n } from '@/contexts/I18nContext'
import { TOKENS } from '@/lib/tokens'

// ── Types ─────────────────────────────────────────────────────────────────────

export type CareerStage = 'student' | 'junior' | 'mid' | 'senior' | 'management'

interface Stage {
  value: CareerStage
  icon:  string
}

// Title and subtitle live in the dictionaries (signup.career_stages), indexed
// positionally against this list — keep the two in the same order.
const STAGES: Stage[] = [
  { value: 'student',    icon: '🎓' },
  { value: 'junior',     icon: '🌱' },
  { value: 'mid',        icon: '⚡' },
  { value: 'senior',     icon: '🎯' },
  { value: 'management', icon: '🏆' },
]

// ── Component ─────────────────────────────────────────────────────────────────

interface CareerStageCardsProps {
  value:     CareerStage | ''
  onChange:  (v: CareerStage) => void
  disabled?: boolean
}

export function CareerStageCards({
  value,
  onChange,
  disabled = false,
}: CareerStageCardsProps) {
  const { t } = useI18n()
  const stages = t.signup.career_stages
  return (
    <div
      className="grid grid-cols-2 gap-2 sm:gap-2.5"
      role="radiogroup"
      aria-label={t.signup.page.career_stage}
    >
      {STAGES.map((stage, i) => {
        const selected = value === stage.value
        return (
          <button
            key={stage.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => { if (!disabled) onChange(stage.value) }}
            className={[
              'relative flex flex-col gap-1 rounded-xl border-2 px-3.5 py-3 text-start',
              'transition-all duration-150 select-none outline-none',
              'focus-visible:ring-2 focus-visible:ring-offset-1',
              disabled
                ? 'opacity-50 cursor-not-allowed'
                : 'cursor-pointer hover:border-teal-300 hover:bg-teal-50/50 active:scale-[0.98]',
              selected
                ? 'bg-teal-50 border-teal-500 shadow-sm'
                : 'bg-white border-slate-200',
            ].join(' ')}
            style={
              stage.value === 'management'
                ? { gridColumn: '1 / -1' }
                : undefined
            }
          >
            {/* Selected checkmark */}
            {selected && (
              <span
                className="absolute top-2.5 end-2.5 w-4 h-4 rounded-full flex items-center justify-center text-white"
                style={{ background: TOKENS.color.primary }}
                aria-hidden="true"
              >
                <svg
                  width="9" height="9" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="3.5"
                  strokeLinecap="round" strokeLinejoin="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </span>
            )}

            <span className="text-xl leading-none">{stage.icon}</span>
            <span
              className="text-[13px] font-semibold leading-tight"
              style={{ color: selected ? TOKENS.color.primary : '#1e293b' }}
            >
              {stages[i].title}
            </span>
            <span className="text-[11px] leading-relaxed text-slate-400 hidden sm:block">
              {stages[i].subtitle}
            </span>
          </button>
        )
      })}
    </div>
  )
}
