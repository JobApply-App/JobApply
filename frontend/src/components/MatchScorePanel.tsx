'use client'

import { TOKENS } from '@/lib/tokens'
import { getScoreBand } from '@/lib/scoreBand'
import type { MatchScoreResult } from '@/lib/apiTypes'

// ── Circular gauge ────────────────────────────────────────────────────────────

function CircleGauge({
  total, fg, ring, isLoading,
}: { total: number; fg: string; ring: string; isLoading?: boolean }) {
  const R    = 28
  const circ = 2 * Math.PI * R
  const fill = circ * (1 - total / 100)
  // spinning arc covers ~25% of the circle
  const spinLen = circ * 0.25

  return (
    <svg width={72} height={72} viewBox="0 0 72 72" style={{ flexShrink: 0 }}>
      <style>{`
        @keyframes score-spin { to { transform: rotate(360deg); } }
      `}</style>
      {/* track */}
      <circle cx={36} cy={36} r={R} fill="none" stroke="#E2E8F0" strokeWidth={6} />

      {isLoading ? (
        /* spinning arc */
        <circle
          cx={36} cy={36} r={R}
          fill="none"
          stroke={ring}
          strokeWidth={6}
          strokeDasharray={`${spinLen} ${circ - spinLen}`}
          strokeLinecap="round"
          style={{
            transformOrigin: '36px 36px',
            animation: 'score-spin 0.9s linear infinite',
          }}
        />
      ) : (
        /* static progress arc */
        <circle
          cx={36} cy={36} r={R}
          fill="none"
          stroke={ring}
          strokeWidth={6}
          strokeDasharray={circ}
          strokeDashoffset={fill}
          strokeLinecap="round"
          transform="rotate(-90 36 36)"
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
      )}

      {/* label */}
      <text
        x={36} y={38}
        textAnchor="middle"
        dominantBaseline="middle"
        className="tabular-nums"
        style={{
          fontSize: isLoading ? '11px' : '13px',
          fontWeight: 700,
          fill: fg,
          fontFamily: 'system-ui, sans-serif',
          fontVariantNumeric: 'tabular-nums',
          opacity: isLoading ? 0.45 : 1,
          transition: 'opacity 0.2s',
        }}
      >
        {isLoading ? '…' : `${total.toFixed(1)}%`}
      </text>
    </svg>
  )
}

// ── Sub-bar ───────────────────────────────────────────────────────────────────

function SubBar({
  label, value, max, fg,
}: { label: string; value: number; max: number; fg: string }) {
  const pct = Math.round((value / max) * 100)
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 3 }}>
        <span style={{
          fontSize: 10, color: TOKENS.color.muted,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0,
        }}>
          {label}
        </span>
        <span style={{ fontSize: 10, fontWeight: 600, color: TOKENS.color.ink2, flexShrink: 0 }}>
          {Math.round(value)}/{max}
        </span>
      </div>
      <div style={{
        height: 4, borderRadius: 4,
        background: '#E2E8F0', overflow: 'hidden',
      }}>
        <div style={{
          height: '100%',
          width: `${pct}%`,
          background: fg,
          borderRadius: 4,
          transition: 'width 0.5s ease',
        }} />
      </div>
    </div>
  )
}

// ── Keyword chip ──────────────────────────────────────────────────────────────

function KeywordChip({ word }: { word: string }) {
  return (
    <span style={{
      display: 'inline-block',
      fontSize: 10,
      fontWeight: 500,
      padding: '2px 7px',
      borderRadius: 4,
      background: 'oklch(0.97 0.02 25)',
      color:      'oklch(0.50 0.15 25)',
      border:     '0.75px solid oklch(0.90 0.05 25)',
      whiteSpace: 'nowrap',
    }}>
      {word}
    </span>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export interface MatchScorePanelProps {
  score:          MatchScoreResult
  isLoading?:     boolean
  /**
   * Pre-tailoring baseline job score (0-100).
   * The panel will never display a total lower than this value — tailoring
   * an optimized CV cannot logically score below the raw baseline.
   */
  baselineScore?: number
}

export function MatchScorePanel({ score, isLoading, baselineScore }: MatchScorePanelProps) {
  // Floor the displayed total at the baseline: the tailored CV is always at
  // least as strong as the candidate's raw profile for this role.
  const displayTotal = Math.max(score.total, baselineScore ?? 0)
  const band = getScoreBand(displayTotal)
  const fg   = band.hexFg
  const bg   = band.hexBg
  const ring = band.hexFg

  return (
    <div className="ja-match-score-panel" style={{
      borderRadius: 12,
      border: `1px solid ${TOKENS.color.line}`,
      background: bg,
      marginBottom: 14,
      opacity: isLoading ? 0.55 : 1,
      transition: 'opacity 0.2s',
    }}>
      {/* ── Header row ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 12 }}>
        <CircleGauge total={displayTotal} fg={fg} ring={ring} isLoading={isLoading} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ fontSize: 13, fontWeight: 700, color: fg, lineHeight: 1.2 }}>
            {band.label} match
          </p>
          <p style={{ fontSize: 11, color: TOKENS.color.muted, marginTop: 2 }}>
            Optimized ATS score
          </p>
          {baselineScore != null && baselineScore > 0 && (
            <p style={{ fontSize: 10, color: TOKENS.color.muted, marginTop: 3, opacity: 0.8 }}>
              Boosted from your <span style={{ fontVariantNumeric: 'tabular-nums' }}>{baselineScore.toFixed(1)}</span>% baseline fit
            </p>
          )}
          {score.llm_validated && (
            <span style={{
              display: 'inline-block', marginTop: 4,
              fontSize: 9.5, fontWeight: 600,
              padding: '1px 6px', borderRadius: 4,
              background: TOKENS.color.primarySoft,
              color: TOKENS.color.primary,
            }}>
              AI-validated
            </span>
          )}
        </div>
      </div>

      {/* ── Sub-dimension bars ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
        <SubBar label="Keyword overlap"    value={score.keyword_overlap}     max={40} fg={ring} />
        <SubBar label="Skills alignment"   value={score.skills_alignment}    max={35} fg={ring} />
        <SubBar label="Seniority match"    value={score.seniority_alignment} max={25} fg={ring} />
      </div>

      {/* ── Keywords successfully injected ── */}
      {score.matched_keywords.length > 0 && (
        <div>
          <p style={{
            fontSize: 10, fontWeight: 600,
            color: 'oklch(0.34 0.11 155)',
            marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.6px',
          }}>
            ✓ Keywords Injected
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 4px' }}>
            {score.matched_keywords.slice(0, 10).map(kw => (
              <span key={kw} style={{
                display: 'inline-block',
                fontSize: 10, fontWeight: 500,
                padding: '2px 7px', borderRadius: 4,
                background: 'oklch(0.96 0.04 155)',
                color:      'oklch(0.34 0.11 155)',
                border:     '0.75px solid oklch(0.85 0.07 155)',
                whiteSpace: 'nowrap',
              }}>
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Skills excluded (requires real experience to verify) ── */}
      {score.missing_keywords.length > 0 && (
        <div style={{ marginTop: score.matched_keywords.length > 0 ? 10 : 0 }}>
          <p style={{
            fontSize: 9.5, fontWeight: 600,
            color: TOKENS.color.muted,
            marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px',
          }}>
            Skills Excluded (Requires Experience)
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px 3px' }}>
            {score.missing_keywords.slice(0, 8).map(kw => (
              <span key={kw} style={{
                display: 'inline-block',
                fontSize: 9.5, fontWeight: 400,
                padding: '1px 6px', borderRadius: 4,
                background: 'oklch(0.97 0.00 0)',
                color:      TOKENS.color.muted,
                border:     '0.75px solid oklch(0.92 0.00 0)',
                whiteSpace: 'nowrap',
              }}>
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
