'use client'

import { TOKENS } from '@/lib/tokens'

// ── Types ─────────────────────────────────────────────────────────────────────

export type CareerStage = 'student' | 'junior' | 'mid' | 'senior' | 'management'

interface Stage {
  value:    CareerStage
  icon:     string
  title:    string
  subtitle: string
}

const STAGES: Stage[] = [
  {
    value:    'student',
    icon:     '🎓',
    title:    'Student',
    subtitle: 'Currently studying or recently graduated',
  },
  {
    value:    'junior',
    icon:     '🌱',
    title:    'Junior',
    subtitle: '0 – 2 years of professional experience',
  },
  {
    value:    'mid',
    icon:     '⚡',
    title:    'Mid-Level',
    subtitle: '3 – 6 years, driving impact independently',
  },
  {
    value:    'senior',
    icon:     '🎯',
    title:    'Senior',
    subtitle: '7+ years, leading projects & mentoring',
  },
  {
    value:    'management',
    icon:     '🏆',
    title:    'Management',
    subtitle: 'Leading teams or functions',
  },
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
  return (
    <div
      className="grid grid-cols-2 gap-2 sm:gap-2.5"
      role="radiogroup"
      aria-label="Career Stage"
    >
      {STAGES.map(stage => {
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
              'relative flex flex-col gap-1 rounded-xl border-2 px-3.5 py-3 text-left',
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
                className="absolute top-2.5 right-2.5 w-4 h-4 rounded-full flex items-center justify-center text-white"
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
              {stage.title}
            </span>
            <span className="text-[11px] leading-relaxed text-slate-400 hidden sm:block">
              {stage.subtitle}
            </span>
          </button>
        )
      })}
    </div>
  )
}
