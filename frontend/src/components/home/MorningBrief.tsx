'use client'
// The morning brief: the top of the home page (design direction 1, chosen by
// Ron on 27.11). What the night's search found, in one sentence, the number
// behind it, three steps for today, and the jobs worth opening first.
// Motion follows the landing page: content rises out of a soft blur in a short
// stagger, numbers count up, score rings draw. All of it collapses to the end
// state under reduced motion (OS setting or the accessibility menu).

import { useEffect, useState, type ReactNode } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { useAuth } from '@/contexts/AuthContext'
import { resolveDisplayName, getGreetingName } from '@/lib/nameUtils'
import { timeOfDay, todayLabel } from '@/lib/greeting'
import { headline, loadDone, markDone, type StepId } from '@/lib/morningBrief'
import type { ApiFeedJob } from '@/lib/apiTypes'
import { buttonClasses } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { ScoreRing } from '../ui/ScoreRing'
import { CompanyLogo } from '../ui/CompanyLogo'
import { localizeReason } from '@/lib/reasonLabel'
import { useReducedMotion, useCountUp } from '@/hooks/useMotion'
import { ArrowIcon, CheckIcon, FileIcon, FilterIcon, SparkIcon } from '../icons'

const delay = (ms: number) => ({ animationDelay: `${ms}ms` })

// ── Hero: the sentence and the number ────────────────────────────────────────

export function BriefHero({ strong, fresh, apps, avg, loading, refreshing, onReview, onAriel }: {
  strong:     number
  fresh:      number
  apps:       number | null
  avg:        number | null
  loading:    boolean
  /** Set while a last-known snapshot is showing; replaces the status line. */
  refreshing: string | null
  onReview:   () => void
  onAriel:    () => void
}) {
  const { t, locale } = useI18n()
  const O = t.overview, B = O.brief
  const { user } = useAuth()
  const reduced = useReducedMotion()
  const count = useCountUp(loading ? null : fresh, reduced)

  const name = getGreetingName(resolveDisplayName(user?.email, user?.user_metadata as Record<string, unknown> | null))
  // The clock is read only once the user is known, so the server render
  // (no user) never disagrees with the client about the time of day.
  const greeting = user
    ? (name ? O.greeting.replace('{greeting}', O[`greeting_${timeOfDay()}`]).replace('{name}', name) : O[`greeting_${timeOfDay()}`])
    : null
  const h = headline(strong, fresh)
  const lead = h === 'strong_one' ? B.strong_one
    : h === 'strong_many' ? B.strong_many.replace('{n}', String(strong))
    : h === 'fresh' ? B.fresh.replace('{n}', String(fresh))
    : B.searching

  return (
    <section className="grid gap-8 lg:gap-12 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] items-center">
      <div>
        <p aria-live="polite" className="animate-ja-reveal flex items-center gap-2.5 text-[14px] sm:text-[15px] text-slate-500">
          <span className="relative flex h-2 w-2" aria-hidden>
            <span className="absolute inset-0 rounded-full bg-ja-verified opacity-60 animate-ping" />
            <span className="relative h-2 w-2 rounded-full bg-ja-verified" />
          </span>
          {user && <>{todayLabel(locale)} · </>}{refreshing ?? B.status}
        </p>
        <h1 dir="auto" className="mt-4 text-[36px] sm:text-[50px] lg:text-[56px] leading-[1.05] font-extrabold tracking-[-0.045em] text-slate-900 text-start">
          {greeting && <span className="block animate-ja-reveal" style={delay(70)}>{greeting}.</span>}
          {loading
            ? <span aria-hidden className="mt-3 block h-10 sm:h-12 w-4/5 rounded-xl bg-slate-100 animate-pulse" />
            : <span className="block text-slate-500 animate-ja-reveal" style={delay(150)}>{lead}</span>}
        </h1>
        <p className="mt-5 max-w-[34rem] text-[17px] sm:text-[19px] leading-relaxed text-slate-600 animate-ja-reveal" style={delay(230)}>
          {fresh > 0 ? B.sub_fresh.replace('{n}', String(fresh)) : B.sub_quiet}
        </p>
        <div className="mt-7 flex flex-wrap gap-3 animate-ja-reveal" style={delay(310)}>
          <button onClick={onReview} className={buttonClasses({ variant: 'primary', size: 'lg' })}>{B.cta_review}</button>
          <button onClick={onAriel} className={buttonClasses({ variant: 'quiet', size: 'lg' })}>{B.cta_ariel}</button>
        </div>
      </div>

      <div
        className="relative overflow-hidden rounded-[28px] bg-white border border-slate-100 shadow-floating p-6 sm:p-8 animate-ja-reveal"
        style={delay(260)}
      >
        <span aria-hidden className="ja-sheen" />
        <div className="text-[64px] sm:text-[84px] leading-[0.9] font-extrabold tracking-[-0.05em] text-ja-harbor tabular-nums">
          {count === null ? <Skeleton className="h-[58px] sm:h-[76px] w-32 rounded-2xl" /> : count}
        </div>
        <p className="mt-3 text-[15px] sm:text-[16px] text-slate-500">{B.new_label}</p>
        <dl className="mt-6 pt-5 border-t border-slate-100 grid grid-cols-3 gap-3">
          <Stat label={B.stat_strong} value={loading ? null : String(strong)} accent />
          <Stat label={B.stat_apps}   value={apps === null ? null : String(apps)} />
          <Stat label={B.stat_avg}    value={avg === null ? null : avg.toFixed(1)} />
        </dl>
      </div>
    </section>
  )
}

function Stat({ label, value, accent = false }: { label: string; value: string | null; accent?: boolean }) {
  return (
    <div className="flex flex-col-reverse">
      <dt className="mt-1 text-[12.5px] sm:text-[13px] leading-snug text-slate-500">{label}</dt>
      <dd className={`text-[22px] sm:text-[26px] font-extrabold tracking-[-0.03em] tabular-nums ${accent ? 'text-teal-700' : 'text-slate-900'}`}>
        {value ?? <Skeleton className="h-7 w-10 rounded-lg" />}
      </dd>
    </div>
  )
}

// ── Today's steps ────────────────────────────────────────────────────────────

const TILE_PRODUCT = 'linear-gradient(135deg, #14B8A6 0%, #0F766E 100%)'
const TILE_ARIEL   = 'linear-gradient(135deg, #4592A6 0%, #2A6577 100%)'

export function TodaySteps({ userId, topJob, hasMatches, onReview, onTailor, onAriel }: {
  userId:     string
  topJob:     ApiFeedJob | null
  hasMatches: boolean
  onReview:   () => void
  onTailor:   (jobId: string) => void
  onAriel:    () => void
}) {
  const B = useI18n().t.overview.brief
  const [done, setDone] = useState<StepId[]>([])
  useEffect(() => { if (userId) setDone(loadDone(userId)) }, [userId])

  const steps: { id: StepId; title: string; body: string; icon: ReactNode; tile: string; act: () => void }[] = []
  if (hasMatches) steps.push({ id: 'review', ...B.step_review, icon: <FilterIcon s={21} />, tile: TILE_PRODUCT, act: onReview })
  if (topJob) steps.push({
    id: 'tailor',
    title: B.step_tailor.title.replace('{company}', topJob.company),
    body:  B.step_tailor.body.replace('{score}', topJob.match_score.toFixed(1)),
    icon: <FileIcon s={21} />, tile: TILE_PRODUCT, act: () => onTailor(topJob.job_id),
  })
  steps.push({ id: 'ariel', ...B.step_ariel, icon: <SparkIcon s={21} />, tile: TILE_ARIEL, act: onAriel })

  const doneCount = steps.filter(s => done.includes(s.id)).length
  const open = (id: StepId, act: () => void) => {
    if (userId) setDone(markDone(userId, id))
    act()
  }

  return (
    <section aria-labelledby="brief-steps">
      <div className="flex items-baseline justify-between gap-4 flex-wrap animate-ja-reveal" style={delay(380)}>
        <h2 id="brief-steps" className="text-[26px] sm:text-[30px] font-extrabold tracking-[-0.035em] text-slate-900">{B.steps_title}</h2>
        <span className="text-[14px] sm:text-[15px] text-slate-500">
          {B.steps_done.replace('{n}', String(doneCount)).replace('{total}', String(steps.length))}
        </span>
      </div>
      <ol className="mt-5 grid gap-4 sm:gap-5 md:grid-cols-3">
        {steps.map((s, i) => {
          const isDone = done.includes(s.id)
          return (
            <li key={s.id} className="animate-ja-reveal" style={delay(440 + i * 80)}>
              <button
                onClick={() => open(s.id, s.act)}
                className="group w-full h-full text-start rounded-[24px] bg-white border border-slate-100 p-6 shadow-elevation-2 transition-[transform,box-shadow] duration-ja-ui ease-ja-out sm:hover:-translate-y-[3px] sm:hover:shadow-floating active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40"
              >
                <span className="flex items-center justify-between">
                  <span
                    className={`h-11 w-11 rounded-[14px] flex items-center justify-center text-white transition-opacity duration-ja-ui ${isDone ? 'opacity-50' : ''}`}
                    style={{ background: s.tile, boxShadow: '0 8px 18px -8px rgba(19,78,74,0.55)' }}
                    aria-hidden
                  >
                    {s.icon}
                  </span>
                  {isDone && (
                    <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-emerald-700">
                      <span className="h-6 w-6 rounded-full bg-emerald-500 text-white flex items-center justify-center"><CheckIcon s={13} /></span>
                      {B.done}
                    </span>
                  )}
                </span>
                <span dir="auto" className="mt-5 block text-[18px] sm:text-[19px] font-bold tracking-[-0.02em] text-slate-900 text-start">{s.title}</span>
                <span className="mt-1.5 block text-[15px] leading-relaxed text-slate-500">{s.body}</span>
              </button>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

// ── The jobs worth opening first ─────────────────────────────────────────────

export function TopMatchCards({ jobs, loading, onOpen, onSeeAll }: {
  jobs:     ApiFeedJob[]
  loading:  boolean
  onOpen:   (jobId: string) => void
  onSeeAll: () => void
}) {
  const { t, locale } = useI18n()
  const O = t.overview
  return (
    <section data-tour="top-matches" aria-labelledby="brief-top">
      <div className="flex items-baseline justify-between gap-4 animate-ja-reveal" style={delay(560)}>
        <h2 id="brief-top" className="text-[26px] sm:text-[30px] font-extrabold tracking-[-0.035em] text-slate-900">{O.top_matches}</h2>
        <button onClick={onSeeAll} className="inline-flex items-center gap-1.5 min-h-[44px] text-[14px] font-medium text-teal-700 sm:hover:text-teal-900 transition-colors">
          {O.see_all} <ArrowIcon s={12} />
        </button>
      </div>
      {loading ? (
        <div className="mt-5 grid gap-4 sm:gap-5 md:grid-cols-3">
          {[1, 0.7, 0.4].map(o => (
            <div key={o} className="rounded-[24px] bg-white border border-slate-100 p-5 shadow-elevation-1 flex gap-4" style={{ opacity: o }}>
              <Skeleton className="h-16 w-16 rounded-full shrink-0" />
              <div className="flex-1 space-y-2 pt-1"><Skeleton className="h-4 w-4/5" /><Skeleton className="h-3 w-1/2" /></div>
            </div>
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <p className="mt-4 text-[15px] text-slate-500">{O.no_matches}</p>
      ) : (
        <div className="mt-5 grid gap-4 sm:gap-5 md:grid-cols-3">
          {jobs.map((j, i) => {
            const location = (locale === 'he' && j.location_he) || j.location
            return (
              <button
                key={j.job_id}
                onClick={() => onOpen(j.job_id)}
                className="group text-start rounded-[24px] bg-white border border-slate-100 p-5 shadow-elevation-2 flex flex-col gap-4 transition-[transform,box-shadow] duration-ja-ui ease-ja-out sm:hover:-translate-y-[3px] sm:hover:shadow-floating active:scale-[0.98] animate-ja-reveal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40"
                style={delay(620 + i * 90)}
              >
                <span className="flex items-start gap-4">
                  <ScoreRing score={j.match_score} />
                  <span className="min-w-0 pt-1">
                    {/* dir="auto" keeps a Hebrew title readable in the English UI; the
                        alignment follows the UI, so the three titles line up. */}
                    <span dir="auto" className="block text-[17px] leading-snug font-bold tracking-[-0.02em] text-slate-900 line-clamp-2" style={{ textAlign: locale === 'he' ? 'right' : 'left' }}>{j.title}</span>
                    <span className="mt-1.5 flex items-center gap-2 text-[14px] text-slate-500 min-w-0">
                      <CompanyLogo company={j.company} size={22} radius={6} />
                      <span className="truncate">{j.company}{location && <> · {location}</>}</span>
                    </span>
                  </span>
                </span>
                {j.reasons.length > 0 && (
                  <span className="flex flex-wrap gap-1.5">
                    {j.reasons.slice(0, 3).map(r => (
                      <span key={r.label} dir="auto" className="inline-flex items-center h-7 px-2.5 rounded-full bg-slate-100 text-[12.5px] text-slate-700">{localizeReason(r.label, t.job_card.reason_labels)}</span>
                    ))}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}
