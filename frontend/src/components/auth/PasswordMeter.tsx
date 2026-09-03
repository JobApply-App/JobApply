'use client'

import { useI18n } from '@/contexts/I18nContext'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PwChecks {
  length:    boolean
  uppercase: boolean
  number:    boolean
  special:   boolean
}

export type PwLevel = 'empty' | 'weak' | 'fair' | 'strong'

export interface PwResult {
  score:  number   // 0–4
  level:  PwLevel
  checks: PwChecks
}

// ── Analysis ──────────────────────────────────────────────────────────────────

export function evaluatePassword(pw: string): PwResult {
  const checks: PwChecks = {
    length:    pw.length    >= 8,
    uppercase: /[A-Z]/.test(pw),
    number:    /[0-9]/.test(pw),
    special:   /[^A-Za-z0-9]/.test(pw),
  }
  const score = Object.values(checks).filter(Boolean).length
  const level: PwLevel =
    pw.length === 0 ? 'empty'  :
    score <= 1      ? 'weak'   :
    score <= 2      ? 'fair'   :
                      'strong'
  return { score, level, checks }
}

// ── Bar colours ───────────────────────────────────────────────────────────────

const BAR_COLOR: Record<PwLevel, string> = {
  empty:  '#E2E8F0',
  weak:   '#EF4444',   // red-500
  fair:   '#EAB308',   // yellow-500
  strong: '#22C55E',   // green-500
}

// Level labels and requirement text come from the dictionaries; only the
// check keys live here. REQUIREMENT_KEYS is indexed positionally against
// signup.password_rules — keep the two in the same order.
const REQUIREMENT_KEYS: ReadonlyArray<keyof PwChecks> = [
  'length', 'uppercase', 'number', 'special',
]

// ── Component ─────────────────────────────────────────────────────────────────

interface PasswordMeterProps {
  password: string
}

export function PasswordMeter({ password }: PasswordMeterProps) {
  const { t } = useI18n()
  const { score, level, checks } = evaluatePassword(password)

  if (password.length === 0) return null

  const color = BAR_COLOR[level]

  return (
    <div className="mt-2.5 space-y-2">
      {/* Segmented bar: 4 segments, colour fills from left */}
      <div className="flex gap-1">
        {[1, 2, 3, 4].map(seg => (
          <div
            key={seg}
            className="h-1.5 flex-1 rounded-full transition-colors duration-200"
            style={{ backgroundColor: score >= seg ? color : '#E2E8F0' }}
          />
        ))}
      </div>

      {/* Level label */}
      <p className="text-[11.5px] font-semibold transition-colors" style={{ color }}>
        {level === 'empty' ? '' : t.signup.password_levels[level]}
      </p>

      {/* Requirements checklist */}
      <ul className="space-y-1">
        {REQUIREMENT_KEYS.map((key, i) => {
          const met = checks[key]
          return (
            <li key={key}
              className="flex items-center gap-1.5 text-[11px] transition-colors"
              style={{ color: met ? '#16a34a' : '#94a3b8' }}
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="3" strokeLinecap="round"
                strokeLinejoin="round" aria-hidden="true" className="flex-shrink-0">
                {met
                  ? <polyline points="20 6 9 17 4 12" />
                  : <><line x1="5" y1="12" x2="19" y2="12" /></>
                }
              </svg>
              {t.signup.password_rules[i]}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
