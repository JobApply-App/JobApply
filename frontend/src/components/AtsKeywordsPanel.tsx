'use client'
import { useState, useEffect } from 'react'
import { fetchAtsKeywords, ensureFreshToken, getAuthHeaders } from '@/lib/api'
import { getScoreBand } from '@/lib/scoreBand'
import type { AtsKeywordsResponse } from '@/lib/apiTypes'

// ── ATS Breakdown ─────────────────────────────────────────────────────────────
//
// Clean, data-dense replacement for the old bulky keyword-gap box. Three
// micro-sections, no coverage meters, no oversized pills:
//
//   ✓ KEYWORDS INJECTED                    — JD keywords covered by the profile
//   SKILLS EXCLUDED (REQUIRES EXPERIENCE)  — JD keywords with no evidence
//   CONFIDENCE SNAPSHOT                    — verified skills with a status dot
//
// The panel is mounted only after the user opens the "ATS Breakdown"
// disclosure in JobCard, so it auto-fetches on mount — the disclosure click
// is the intent signal; no second "Analyse" click needed.

function SpinnerIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 0.8s linear infinite' }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

// ── Section atoms ─────────────────────────────────────────────────────────────

function SectionLabel({ children, tone = 'slate' }: {
  children: React.ReactNode
  tone?: 'emerald' | 'slate'
}) {
  return (
    <p className={`text-[10px] font-bold tracking-widest uppercase mb-1.5 ${
      tone === 'emerald' ? 'text-emerald-700' : 'text-slate-400'
    }`}>
      {children}
    </p>
  )
}

function MicroChip({ label, tone }: { label: string; tone: 'injected' | 'excluded' }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10.5px] font-medium ${
      tone === 'injected'
        ? 'bg-emerald-50 text-emerald-700'
        : 'bg-slate-50 text-slate-500 border border-slate-100'
    }`}>
      {label}
    </span>
  )
}

// ── Confidence snapshot ───────────────────────────────────────────────────────
//
// Verified skills relevant to this JD, each with a micro status dot:
//   emerald ≥ 70 (verified) · amber 40–69 (partial) · slate < 40 (weak)

interface TrustEntity {
  entity_id:        string
  name:             string
  confidence_score: number
}

// Solid dot color pulled from the same 5-tier Meridian V2 band (§2.3) as
// every other score-magnitude indicator — swaps the pale `text-*` shade for
// its saturated `bg-*` equivalent since a 6px dot needs to read at a glance.
function confidenceDot(score: number): string {
  return getScoreBand(score).text.replace('text-', 'bg-')
}

function ConfidenceSnapshot({ entities }: { entities: TrustEntity[] }) {
  if (entities.length === 0) return null
  return (
    <div>
      <SectionLabel>Confidence Snapshot</SectionLabel>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {entities.map(e => (
          <span key={e.entity_id} className="inline-flex items-center gap-1.5 text-[11px] text-slate-600 tabular-nums">
            <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${confidenceDot(e.confidence_score)}`} />
            {e.name} ({e.confidence_score.toFixed(1)}%)
          </span>
        ))}
      </div>
    </div>
  )
}

/** Trust entities whose name overlaps any JD keyword — the JD-relevant subset. */
function relevantEntities(entities: TrustEntity[], keywords: string[]): TrustEntity[] {
  const kws = keywords.map(k => k.toLowerCase())
  return entities
    .filter(e => {
      const name = e.name.toLowerCase()
      return kws.some(k => name.includes(k) || k.includes(name))
    })
    .sort((a, b) => b.confidence_score - a.confidence_score)
    .slice(0, 6)
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  jobId:   string
  hasJd:   boolean          // whether JD text is available — show hint if not
  userId?: string           // enables the Confidence Snapshot section
}

export function AtsKeywordsPanel({ jobId, hasJd, userId }: Props) {
  const [data,     setData]     = useState<AtsKeywordsResponse | null>(null)
  const [entities, setEntities] = useState<TrustEntity[]>([])
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  // Auto-fetch on mount — the panel only mounts once the user opens the
  // "ATS Breakdown" disclosure, so the click already expressed intent.
  useEffect(() => {
    if (!hasJd) return
    let cancelled = false
    setLoading(true)
    setError(null)

    const load = async () => {
      try {
        const result = await fetchAtsKeywords(jobId)
        if (cancelled) return
        setData(result)

        // Confidence snapshot — best-effort; never blocks the keyword view.
        if (userId) {
          try {
            await ensureFreshToken()
            const res = await fetch(`/api/profile/${userId}/trust-score`, {
              headers: getAuthHeaders(),
              cache:   'no-store',
            })
            if (res.ok && !cancelled) {
              const trust = await res.json()
              setEntities((trust.entities ?? []) as TrustEntity[])
            }
          } catch { /* snapshot is optional */ }
        }
      } catch (e) {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : String(e)
        setError(msg.includes('400') ? 'Fetch the full JD first (click "View Job Description").' : msg)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [jobId, hasJd, userId])

  if (!hasJd) {
    return (
      <p className="text-[12px] text-slate-400 italic">
        Fetch the full job description first to run the ATS breakdown.
      </p>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2 text-[12px] text-slate-400">
        <SpinnerIcon /> Analysing keywords…
      </div>
    )
  }

  if (error) {
    return (
      <p className="text-[12px] text-rose-600 py-1">{error}</p>
    )
  }

  if (!data) return null

  const injected = data.present
  const excluded = data.missing
  const snapshot = relevantEntities(entities, data.jd_keywords)

  return (
    <div className="space-y-4 py-1">
      {/* ✓ KEYWORDS INJECTED */}
      {injected.length > 0 && (
        <div>
          <SectionLabel tone="emerald">✓ Keywords Injected</SectionLabel>
          <div className="flex flex-wrap gap-1">
            {injected.map(kw => <MicroChip key={kw} label={kw} tone="injected" />)}
          </div>
        </div>
      )}

      {/* SKILLS EXCLUDED (REQUIRES EXPERIENCE) */}
      {excluded.length > 0 && (
        <div>
          <SectionLabel>Skills Excluded (Requires Experience)</SectionLabel>
          <div className="flex flex-wrap gap-1">
            {excluded.map(kw => <MicroChip key={kw} label={kw} tone="excluded" />)}
          </div>
        </div>
      )}

      {/* CONFIDENCE SNAPSHOT */}
      <ConfidenceSnapshot entities={snapshot} />

      {injected.length === 0 && excluded.length === 0 && (
        <p className="text-[12px] text-slate-400 italic">No ATS keywords extracted for this posting.</p>
      )}
    </div>
  )
}
