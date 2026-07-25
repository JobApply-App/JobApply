'use client'

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

const LEVEL_LABEL: Record<PwLevel, string> = {
  empty:  '',
  weak:   'Too weak',
  fair:   'Fair — try adding symbols',
  strong: 'Strong password',
}

const REQUIREMENTS = [
  { key: 'length'    as keyof PwChecks, label: 'At least 8 characters'   },
  { key: 'uppercase' as keyof PwChecks, label: '1 uppercase letter'       },
  { key: 'number'    as keyof PwChecks, label: '1 number'                 },
  { key: 'special'   as keyof PwChecks, label: '1 special character (!@#…)' },
]

// ── Component ─────────────────────────────────────────────────────────────────

interface PasswordMeterProps {
  password: string
}

export function PasswordMeter({ password }: PasswordMeterProps) {
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
        {LEVEL_LABEL[level]}
      </p>

      {/* Requirements checklist */}
      <ul className="space-y-1">
        {REQUIREMENTS.map(req => {
          const met = checks[req.key]
          return (
            <li key={req.key}
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
              {req.label}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
