'use client'
import { useEffect, useState } from 'react'
import { fetchSkillsGap } from '@/lib/api'

// ── Active Skills Gap Analysis (JOB-59) ───────────────────────────────────────
//
// The backend returns free-text LLM analysis (a short bullet-style list, not
// structured missing/matched arrays like the ATS Keyword panel). This
// component parses that prose into individual gap items for clean, scannable
// formatting, falling back to plain paragraphs for any non-bullet lines.

const _BULLET_RE = /^\s*[-•*–◦▪▸→◆]\s+/
const _NUMBER_BULLET_RE = /^\s*\d{1,2}[.)]\s+/

function parseGapLines(text: string): { bullets: string[]; prose: string[] } {
  const lines = text.trim().split('\n').map(l => l.trim()).filter(Boolean)
  const bullets: string[] = []
  const prose: string[] = []
  for (const line of lines) {
    if (_BULLET_RE.test(line) || _NUMBER_BULLET_RE.test(line)) {
      bullets.push(line.replace(_BULLET_RE, '').replace(_NUMBER_BULLET_RE, '').trim())
    } else {
      prose.push(line)
    }
  }
  return { bullets, prose }
}

function SpinnerIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 0.8s linear infinite' }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function GapIcon({ s = 12 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  )
}

interface Props {
  jobId: string
  hasJd: boolean   // whether JD text is available — show hint if not
}

export function SkillsGapPanel({ jobId, hasJd }: Props) {
  const [analysis, setAnalysis] = useState<string | null>(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  // Auto-fetch on mount — the panel only mounts once the user opens the
  // disclosure in JobCard, so that click already signals intent.
  useEffect(() => {
    if (!hasJd) return
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchSkillsGap(jobId)
      .then(res => { if (!cancelled) setAnalysis(res.analysis) })
      .catch(e => {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : String(e)
        setError(msg.includes('400') ? 'Fetch the full JD first (click "View Job Description").' : 'Skills gap analysis failed.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [jobId, hasJd])

  if (!hasJd) {
    return (
      <p className="text-[12px] text-slate-400 italic">
        Fetch the full job description first to run the skills gap analysis.
      </p>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2 text-[12px] text-slate-400">
        <SpinnerIcon /> Analysing gaps…
      </div>
    )
  }

  if (error) {
    return <p className="text-[12px] text-rose-600 py-1">{error}</p>
  }

  if (!analysis || !analysis.trim()) return null

  if (analysis.startsWith('Error:') || analysis.startsWith('Failed to') || analysis.startsWith('Insufficient data')) {
    return <p className="text-[12px] text-slate-400 italic py-1">{analysis}</p>
  }

  const { bullets, prose } = parseGapLines(analysis)

  return (
    <div className="space-y-2 py-1">
      <p className="text-[10px] font-bold tracking-widest uppercase text-amber-700">
        Missing Skills &amp; Requirements
      </p>

      {bullets.length > 0 && (
        <ul className="space-y-1.5">
          {bullets.map((item, i) => (
            <li key={i} className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-700">
              <span className="mt-0.5 shrink-0 text-amber-500"><GapIcon /></span>
              <span className="flex-1">{item}</span>
            </li>
          ))}
        </ul>
      )}

      {prose.map((line, i) => (
        <p key={i} className="text-[12px] leading-relaxed text-slate-600">{line}</p>
      ))}
    </div>
  )
}
