'use client'
import { useCallback, useEffect, useState } from 'react'
import type { ApiFeedJob } from '@/lib/apiTypes'
import { generateDirectPitch } from '@/lib/api'

// ── Direct Pitch Generator (JOB-64) ───────────────────────────────────────────
//
// A short, punchy recruiter pitch (under ~120 words) for one job — a fast
// alternative to a full cover letter. Stateless: unlike the Outreach hiring-
// manager message, the pitch is not persisted server-side; the user edits and
// copies it locally, and re-generating simply asks the LLM again.

function CopyIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}
function CheckIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}
function SpinnerIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 0.8s linear infinite' }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}
function RegenerateIcon({ s = 13 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 .49-3.51" />
    </svg>
  )
}

interface DirectPitchModalProps {
  job:     ApiFeedJob
  onClose: () => void
}

export function DirectPitchModal({ job, onClose }: DirectPitchModalProps) {
  const [pitch,     setPitch]     = useState('')
  const [wordCount, setWordCount] = useState(0)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState<string | null>(null)
  const [copied,    setCopied]    = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setCopied(false)
    try {
      const res = await generateDirectPitch(job.job_id)
      setPitch(res.pitch)
      setWordCount(res.word_count)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Pitch generation failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [job.job_id])

  // Auto-generate on open — the whole point of the modal is a ready pitch.
  useEffect(() => { run() }, [run])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const handleCopy = useCallback(() => {
    if (!pitch) return
    navigator.clipboard.writeText(pitch).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => {})
  }, [pitch])

  return (
    <>
      {/* Backdrop — Meridian V2 §3.2 scrim */}
      <div className="fixed inset-0 z-40 bg-slate-900/55 backdrop-blur-[4px]" onClick={onClose} />

      {/* Panel */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div
          className="w-full max-w-lg rounded-2xl bg-white shadow-floating pointer-events-auto flex flex-col animate-modal-in"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b border-slate-100">
            <div className="min-w-0 flex-1 pr-3">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">
                Direct Pitch
              </p>
              <h3 className="text-[15px] font-bold text-slate-900 leading-snug truncate">
                {job.title}
              </h3>
              <p className="text-[12px] text-slate-400 mt-0.5 truncate">{job.company}</p>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition"
            >
              <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4">
            <p className="text-[11.5px] text-slate-400 mb-2.5">
              A short, punchy recruiter pitch — under ~120 words. Edit freely before copying;
              it isn&apos;t saved anywhere, so regenerating simply asks again.
            </p>

            {loading ? (
              <div className="rounded-lg px-4 py-4 space-y-2.5 bg-slate-50 border border-slate-200" aria-busy="true">
                <div className="flex items-center gap-2 mb-1">
                  <SpinnerIcon s={14} />
                  <span className="text-[12px] font-medium text-ja-primary">Writing your pitch…</span>
                </div>
                {[95, 100, 80, 60].map((w, i) => (
                  <div key={i} className="h-2.5 rounded-full animate-pulse bg-slate-200" style={{ width: `${w}%`, animationDelay: `${i * 100}ms` }} />
                ))}
              </div>
            ) : error ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 flex items-center justify-between gap-3">
                <p className="text-[12.5px] text-rose-700">{error}</p>
                <button onClick={run} className="shrink-0 text-[11.5px] font-medium text-rose-700 underline underline-offset-2">
                  Retry
                </button>
              </div>
            ) : (
              <textarea
                value={pitch}
                onChange={e => setPitch(e.target.value)}
                rows={7}
                className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3.5 py-3 text-[13px] leading-relaxed text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-500/25 focus:border-teal-400 transition"
              />
            )}

            {!loading && !error && (
              <p className="text-[11px] text-slate-400 mt-1.5 tabular-nums">
                {pitch.trim().split(/\s+/).filter(Boolean).length} words
                {wordCount > 0 && wordCount !== pitch.trim().split(/\s+/).filter(Boolean).length ? ' (edited)' : ''}
              </p>
            )}
          </div>

          {/* Footer */}
          <div className="px-5 pb-5 pt-1 flex items-center justify-between">
            <button
              onClick={run}
              disabled={loading}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-medium text-slate-500 hover:text-slate-800 hover:bg-slate-50 transition disabled:opacity-50 disabled:pointer-events-none"
            >
              <RegenerateIcon /> Regenerate
            </button>
            <div className="flex items-center gap-2">
              <button
                onClick={onClose}
                className="h-8 px-4 rounded-lg text-[12.5px] font-medium text-slate-600 border border-slate-200 hover:bg-slate-50 transition"
              >
                Close
              </button>
              <button
                onClick={handleCopy}
                disabled={loading || !!error || !pitch}
                className={`inline-flex items-center gap-1.5 h-8 px-4 rounded-lg text-[12.5px] font-semibold transition active:scale-[0.97] disabled:opacity-40 disabled:pointer-events-none ${
                  copied
                    ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                    : 'bg-ja-primary text-white hover:bg-ja-primaryHover'
                }`}
              >
                {copied ? <><CheckIcon /> Copied!</> : <><CopyIcon /> Copy</>}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
