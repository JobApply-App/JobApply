'use client'
// Matches, one at a time (design direction 2, Ron 27.11). The same list the
// feed shows, filters and search included, but the user meets one job, sees
// why it fits, and decides: tailor a CV, save it, or set it aside. The rest
// wait in a short queue on the side. The full card, with every tool it has,
// opens under the decision for whoever wants the details.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import type { ApiFeedJob } from '@/lib/apiTypes'
import { localizeReason } from '@/lib/reasonLabel'
import { briefIn } from '@/lib/fitBrief'
import { moveCursor, resolveIndex, type FocusCursor } from '@/lib/focusQueue'
import { ScoreRing } from '../ui/ScoreRing'
import { CompanyLogo } from '../ui/CompanyLogo'
import { getScoreBand } from '@/lib/scoreBand'
import { buttonClasses } from '../ui/Button'
import { JobCard } from '../JobCard'

const UP_NEXT = 5

export function FocusView({
  jobs, userId, topFitThreshold, belowThresholdIds, paused,
  onSkip, onSave, onTailorCV, onInteractionChange, onMarkApplied,
}: {
  jobs:              ApiFeedJob[]
  userId?:           string
  topFitThreshold:   number
  belowThresholdIds: ReadonlySet<string>
  /** True while a modal of the feed's own is open: keys do nothing. */
  paused:            boolean
  onSkip:            (id: string) => void
  onSave:            (id: string) => void
  onTailorCV:        (job: ApiFeedJob) => void
  onInteractionChange: (id: string, active: boolean) => void
  onMarkApplied:     (id: string) => void
}) {
  const { t, locale } = useI18n()
  const F = t.job_feed.focus
  const J = t.job_card

  const ids = useMemo(() => jobs.map(j => j.job_id), [jobs])
  const [cursor, setCursor] = useState<FocusCursor>({ id: null, idx: 0 })
  const [details, setDetails] = useState(false)
  const idx = resolveIndex(ids, cursor)
  const job = jobs[idx] as ApiFeedJob | undefined

  // Details close when the job changes; each job starts as a decision.
  useEffect(() => { setDetails(false) }, [job?.job_id])

  const move = useCallback((step: number) => setCursor(c => moveCursor(ids, c, step)), [ids])
  const jump = useCallback((i: number) => setCursor({ id: ids[i] ?? null, idx: i }), [ids])

  const save = useCallback(() => {
    if (!job) return
    onSave(job.job_id)
    // Saving keeps the job on the list; the next one is the natural step.
    // Un-saving is a correction, so it stays put.
    if (job.status !== 'saved') move(1)
  }, [job, onSave, move])

  // A skipped job leaves the list and the next one takes its place, so the
  // cursor keeps its position and lets go of the id.
  const skip = useCallback(() => {
    if (!job) return
    setCursor({ id: null, idx })
    onSkip(job.job_id)
  }, [job, idx, onSkip])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (paused || e.metaKey || e.ctrlKey || e.altKey) return
      const el = e.target as HTMLElement | null
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return
      if (dialogOpen()) return
      const k = e.key.toLowerCase()
      if (k === 'j') move(1)
      else if (k === 'k') move(-1)
      else if (k === 's') save()
      else if (k === 'x') skip()
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [paused, move, save, skip])

  if (!job) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-14 text-center shadow-elevation-1">
        <p className="text-[17px] font-semibold text-slate-900">{F.done_title}</p>
        <p className="mt-1.5 text-[14px] text-slate-500">{F.done_body}</p>
        {ids.length > 0 && (
          <button onClick={() => jump(0)} className={`mt-5 ${buttonClasses({ variant: 'secondary', size: 'sm' })}`}>
            {F.start_over}
          </button>
        )}
      </div>
    )
  }

  const location = (locale === 'he' && job.location_he) || job.location
  const fits = job.reasons.filter(r => r.kind !== 'neg')
  const gaps = job.reasons.filter(r => r.kind === 'neg')
  const next = jobs.slice(idx + 1, idx + 1 + UP_NEXT)
  const saved = job.status === 'saved'
  const brief = briefIn(locale, job.fit_brief, job.fit_brief_translations)

  return (
    <div className="space-y-6">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_240px] lg:items-start">

        {/* ── The one job ──────────────────────────────────────────────── */}
        <article
          key={job.job_id}
          aria-live="polite"
          className="animate-ja-swap rounded-2xl border border-slate-200 bg-white p-5 sm:p-7 shadow-elevation-2"
        >
          <div className="flex items-center justify-between gap-3 text-[12.5px] text-slate-500">
            <span className="tabular-nums">
              {F.progress.replace('{n}', String(idx + 1)).replace('{total}', String(ids.length))}
            </span>
            <span className="inline-flex items-center gap-1">
              <IconButton label={F.prev} disabled={idx === 0} onClick={() => move(-1)}>
                <Chevron dir="back" />
              </IconButton>
              <IconButton label={F.next} disabled={idx >= ids.length - 1} onClick={() => move(1)}>
                <Chevron dir="forward" />
              </IconButton>
            </span>
          </div>
          <div className="mt-2 h-1 rounded-full bg-slate-100 overflow-hidden" aria-hidden>
            <div
              className="h-full rounded-full bg-teal-600 transition-[width] duration-ja-ui ease-ja-out"
              style={{ width: `${((idx + 1) / ids.length) * 100}%` }}
            />
          </div>

          <div className="mt-6 flex flex-col-reverse items-start gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-4">
              <CompanyLogo company={job.company} size={52} />
              <div className="min-w-0">
              <h2 dir="auto" className="text-[22px] sm:text-[26px] font-bold leading-tight tracking-[-0.02em] text-slate-900">
                {job.title}
              </h2>
              <p dir="auto" className="mt-1.5 text-[15px] text-slate-600">
                {job.company}{location && <span className="text-slate-400"> · {location}</span>}
              </p>
              </div>
            </div>
            <ScoreRing score={job.match_score} size={112} stroke={8} label={F.match} quick />
          </div>

          {(fits.length > 0 || gaps.length > 0) && (
            <ul className="mt-6 flex flex-wrap gap-2">
              {fits.map(r => (
                <li key={r.label} dir="auto" className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-3 py-1 text-[13px] text-teal-800">
                  <span aria-hidden className="text-teal-600">✓</span>{localizeReason(r.label, J.reason_labels)}
                </li>
              ))}
              {gaps.map(r => (
                <li key={r.label} dir="auto" className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-[13px] text-amber-800">
                  <span aria-hidden className="text-amber-600">!</span>{localizeReason(r.label, J.reason_labels)}
                </li>
              ))}
            </ul>
          )}

          {brief && (
            <div className="mt-5 rounded-xl px-4 py-3.5" style={{ background: 'rgba(54,122,142,0.07)' }}>
              <p className="text-[12px] font-semibold" style={{ color: '#367A8E' }}>{F.why}</p>
              <p dir="auto" className="mt-1 text-[14px] leading-relaxed text-slate-700">{brief}</p>
            </div>
          )}

          <div className="mt-7 flex flex-wrap items-center gap-2.5">
            <button onClick={() => onTailorCV(job)} className={buttonClasses({ variant: 'primary', size: 'md' })}>
              {J.tailor_cv}
            </button>
            <button onClick={save} aria-pressed={saved} className={buttonClasses({ variant: 'secondary', size: 'md' })}>
              {saved ? J.saved : J.save}
            </button>
            <button onClick={skip} className={buttonClasses({ variant: 'quiet', size: 'md' })}>
              {F.skip}
            </button>
            <button
              onClick={() => setDetails(d => !d)}
              aria-expanded={details}
              className="ms-auto text-[13px] font-medium text-teal-700 hover:underline"
            >
              {details ? F.details_hide : F.details_show}
            </button>
          </div>
          <p className="mt-4 hidden sm:block text-[12px] text-slate-400">{F.keys_hint}</p>
        </article>

        {/* ── Up next ─────────────────────────────────────────────────── */}
        {next.length > 0 && (
          <aside>
            <p className="px-1 text-[12px] font-semibold text-slate-500">{F.up_next}</p>
            <ol className="mt-2 space-y-1">
              {next.map((j, i) => (
                <li key={j.job_id}>
                  <button
                    onClick={() => jump(idx + 1 + i)}
                    className="group flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-start transition-colors duration-ja-ui hover:bg-white active:scale-[0.98]"
                  >
                    <CompanyLogo company={j.company} size={36} />
                    <span className="min-w-0 flex-1">
                      <span dir="auto" className="block truncate text-[13px] font-medium text-slate-800">{j.title}</span>
                      <span dir="auto" className="block truncate text-[12px] text-slate-500">{j.company}</span>
                    </span>
                    <span className="shrink-0 text-[12px] font-bold tabular-nums" style={{ color: getScoreBand(j.match_score).hexFg }}>
                      {j.match_score.toFixed(1)}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </aside>
        )}
      </div>

      {details && (
        <JobCard
          key={`details-${job.job_id}`}
          job={job}
          userId={userId}
          isTopFit={job.match_score > topFitThreshold}
          belowThreshold={belowThresholdIds.has(job.job_id)}
          initialExpanded
          onSkip={() => skip()}
          onSave={() => save()}
          onTailorCV={onTailorCV}
          onInteractionChange={onInteractionChange}
          onMarkApplied={onMarkApplied}
        />
      )}
    </div>
  )
}

// A dialog on screen owns the keyboard. Some stay mounted while closed (the
// Eliya chat is inert and transparent), so only a visible one counts.
function dialogOpen(): boolean {
  return Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"], [aria-modal="true"]')).some(d =>
    !d.closest('[inert]') && (d.checkVisibility?.({ opacityProperty: true, visibilityProperty: true }) ?? d.getClientRects().length > 0),
  )
}

function IconButton({ label, disabled, onClick, children }: {
  label: string; disabled: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="grid h-8 w-8 place-items-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 active:scale-[0.94] disabled:opacity-30 disabled:pointer-events-none"
    >
      {children}
    </button>
  )
}

// Back/forward follow the reading direction: in Hebrew "back" points right.
function Chevron({ dir }: { dir: 'back' | 'forward' }) {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden
      className={dir === 'back' ? 'rtl:rotate-180' : 'rotate-180 rtl:rotate-0'}>
      <polyline points="15 18 9 12 15 6" />
    </svg>
  )
}
