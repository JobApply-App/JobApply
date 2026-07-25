// Meridian V2 score-band system — single source of truth for Match Score /
// Confidence Matrix color mapping across the app (DESIGN_SYSTEM_V2.md §2.3).
// Any change to a boundary or color here must be mirrored in that doc.
//
// This governs score-MAGNITUDE coloring only. It must NOT be applied to
// verification-tier indicators (§6.3: Verified / Certification / Chat-stated /
// Unknown) — those map color to evidence source, not score value, and stay
// on their own tier logic (see TrustDashboard.tsx ProgressBar/CapabilityRow).

export type ScoreBandKey = 'exceptional' | 'strong' | 'moderate' | 'weak' | 'poor'

export interface ScoreBand {
  key:   ScoreBandKey
  label: string
  /** Tailwind utility classes — use in className-based components. */
  text:  string
  bg:    string
  /** Solid hex equivalents — use for inline styles / SVG stroke & fill. */
  hexFg: string
  hexBg: string
}

const BANDS: readonly ScoreBand[] = [
  { key: 'exceptional', label: 'Exceptional', text: 'text-emerald-600', bg: 'bg-emerald-50', hexFg: '#059669', hexBg: '#ECFDF5' },
  { key: 'strong',      label: 'Strong',      text: 'text-teal-600',    bg: 'bg-teal-50',    hexFg: '#0D9488', hexBg: '#F0FDFA' },
  { key: 'moderate',    label: 'Moderate',    text: 'text-amber-600',   bg: 'bg-amber-50',   hexFg: '#D97706', hexBg: '#FFFBEB' },
  { key: 'weak',        label: 'Weak',        text: 'text-orange-600',  bg: 'bg-orange-50',  hexFg: '#EA580C', hexBg: '#FFF7ED' },
  { key: 'poor',        label: 'Poor',        text: 'text-slate-400',   bg: 'bg-slate-100',  hexFg: '#94A3B8', hexBg: '#F1F5F9' },
]

/** Maps a 0-100 score to its Meridian V2 band (§2.3 thresholds). */
export function getScoreBand(score: number): ScoreBand {
  if (score >= 85) return BANDS[0]
  if (score >= 70) return BANDS[1]
  if (score >= 50) return BANDS[2]
  if (score >= 30) return BANDS[3]
  return BANDS[4]
}
