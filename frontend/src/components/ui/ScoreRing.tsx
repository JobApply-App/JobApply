// A match score as a ring that draws to its value (the landing page's score
// motion). Colour from the shared score band. The ring is decoration: the
// number inside is the content, so screen readers read the number alone.

import type { ReactNode } from 'react'
import { getScoreBand } from '@/lib/scoreBand'

export function ScoreRing({ score, size = 64, stroke = 6, label, quick = false, children }: {
  score:     number
  size?:     number
  stroke?:   number
  /** Small text under the number (large rings only). */
  label?:    string
  /** Draw at once, for a ring shown again and again (the focus view). */
  quick?:    boolean
  /** Replaces the number, e.g. a counting-up value. */
  children?: ReactNode
}) {
  const band = getScoreBand(score)
  const r = (size - stroke) / 2 - 1
  const len = 2 * Math.PI * r
  const c = size / 2
  return (
    <span className="relative shrink-0 inline-block" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={c} cy={c} r={r} fill="none" stroke="#F1F5F9" strokeWidth={stroke} />
        <circle
          cx={c} cy={c} r={r} fill="none" stroke={band.hexFg} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={len}
          className={quick ? 'animate-ja-ring-quick' : 'animate-ja-ring'}
          style={{ strokeDashoffset: len * (1 - Math.max(0, Math.min(100, score)) / 100), ['--ring-len' as string]: len }}
        />
      </svg>
      <span className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="font-extrabold tabular-nums text-slate-900"
          style={{ fontSize: Math.round(size * (size >= 100 ? 0.26 : 0.235)), letterSpacing: '-0.04em', lineHeight: 1 }}
        >
          {children ?? score.toFixed(1)}
        </span>
        {label && <span className="mt-1 text-[12px] text-slate-500">{label}</span>}
      </span>
    </span>
  )
}
