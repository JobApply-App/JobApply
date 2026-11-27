'use client'
// The applications journey (design direction 3, Ron 27.11): the four steps
// with how many applications stand at each, then every application with its
// place on the path and the next thing worth doing. Only recorded data: the
// stage and the time of the last change.

import type { ReactNode } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import type { AppListItem } from '@/lib/api'
import { formatRelativeTime } from '@/lib/relativeTime'
import { stageLabel } from '@/lib/stages'
import { STEPS, journeyCounts, nextStep, parseUpdated, stepIndex, type NextStep } from '@/lib/journey'
import { useCountUp, useReducedMotion } from '@/hooks/useMotion'
import { CompanyLogo } from '../ui/CompanyLogo'

// Ink deepens along the path; the offer is the success green.
const STEP_INK = ['#64748B', '#0D9488', '#134E4A', '#059669'] as const

export function JourneyHeader({ items, loading, children }: {
  items: AppListItem[]; loading: boolean; children?: ReactNode
}) {
  const J = useI18n().t.applications.journey
  const active = items.filter(i => stepIndex(i.status) !== -1).length
  const lead = active === 0 ? J.lead_none : active === 1 ? J.lead_one : J.lead_many.replace('{n}', String(active))
  return (
    <div className="animate-ja-reveal flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[34px] sm:text-[48px] font-extrabold leading-[1.02] tracking-[-0.045em] text-slate-900">{J.title}</h1>
        <p className="mt-3 max-w-xl text-[16px] sm:text-[18px] leading-relaxed text-slate-600">
          {loading ? <span className="inline-block h-4 w-64 max-w-full rounded bg-slate-100 animate-pulse align-middle" /> : lead}
        </p>
      </div>
      {children}
    </div>
  )
}

export function JourneyBand({ items, loading }: { items: AppListItem[]; loading: boolean }) {
  const J = useI18n().t.applications.journey
  const reduced = useReducedMotion()
  const counts = journeyCounts(items)
  return (
    <section
      aria-label={J.steps_label}
      // overflow-hidden: each moving light is a line-wide layer slid along
      // the line, which would otherwise widen the page on a phone.
      className="animate-ja-reveal overflow-hidden rounded-[28px] border border-slate-100 bg-white px-4 pb-6 pt-8 sm:px-9 sm:pb-8 sm:pt-9 shadow-floating"
      style={{ animationDelay: '120ms' }}
    >
      <div className="relative mx-[12.5%] h-0.5 bg-gradient-to-r rtl:bg-gradient-to-l from-slate-200 to-teal-200" aria-hidden>
        {!loading && items.length > 0 && <>
          <span className="ja-flow" />
          <span className="ja-flow" style={{ animationDelay: '1.2s' }} />
          <span className="ja-flow" style={{ animationDelay: '2.4s' }} />
        </>}
      </div>
      <ol className="-mt-[15px] grid grid-cols-4 gap-2 sm:gap-3">
        {STEPS.map((s, i) => (
          <Step key={s} n={loading ? null : counts[s]} reduced={reduced} ink={STEP_INK[i]} label={J[s]} sub={J[`${s}_sub`]} />
        ))}
      </ol>
      {!loading && counts.closed > 0 && (
        <p className="mt-5 text-center text-[13px] text-slate-400">{J.closed.replace('{n}', String(counts.closed))}</p>
      )}
    </section>
  )
}

function Step({ n, reduced, ink, label, sub }: { n: number | null; reduced: boolean; ink: string; label: string; sub: string }) {
  const shown = useCountUp(n, reduced)
  const on = (n ?? 0) > 0
  return (
    <li className="flex flex-col items-center text-center">
      <span
        className="h-7 w-7 rounded-full border-4 border-white"
        style={{ background: on ? ink : '#E2E8F0', boxShadow: `0 0 0 1px ${on ? 'rgba(13,148,136,0.25)' : '#E2E8F0'}` }}
        aria-hidden
      />
      <span
        className="mt-3 font-extrabold tabular-nums leading-none tracking-[-0.05em] text-[30px] sm:text-[44px]"
        style={{ color: on ? ink : '#CBD5E1' }}
      >
        {shown ?? '–'}
      </span>
      <span className="mt-1.5 text-[13px] sm:text-[16px] font-semibold text-slate-900">{label}</span>
      <span className="hidden sm:block text-[13px] text-slate-500">{sub}</span>
    </li>
  )
}

const NEXT_TONE: Record<NextStep, string> = {
  offer:     'bg-emerald-50 text-emerald-800',
  prepare:   'bg-[rgba(54,122,142,0.11)] text-[#1F5F70]',
  follow_up: 'bg-[rgba(54,122,142,0.11)] text-[#1F5F70]',
  waiting:   'bg-slate-100 text-slate-500',
  closed:    'bg-slate-100 text-slate-400',
}

export function JourneyRows({ items, action }: { items: AppListItem[]; action: (item: AppListItem) => ReactNode }) {
  const { t, locale } = useI18n()
  const A = t.applications
  const J = A.journey
  const now = new Date()
  return (
    <ol className="animate-ja-reveal rounded-3xl border border-slate-100 bg-white p-2 shadow-elevation-2" style={{ animationDelay: '220ms' }}>
      {items.map((item, row) => {
        const step = stepIndex(item.status)
        const updated = parseUpdated(item.last_update)
        const when = updated ? formatRelativeTime(updated.toISOString(), locale) : null
        const next = nextStep(item.status, updated, now)
        const stage = stageLabel(item.status, A.stages)
        const ink = step === -1 ? '#94A3B8' : STEP_INK[step]
        return (
          <li
            key={item.application_id}
            className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl p-3 sm:p-4 transition-colors duration-ja-ui hover:bg-slate-50"
          >
            <CompanyLogo company={item.company} size={40} />
            <div className="min-w-0 flex-[1_1_200px]">
              {/* dir="auto" keeps an English title readable in the Hebrew UI (it
                  was cut from its start); the alignment still follows the UI,
                  so every title starts on the same side. */}
              <p dir="auto" className="truncate text-[15px] font-bold tracking-[-0.01em] text-slate-900" style={{ textAlign: locale === 'he' ? 'right' : 'left' }}>{item.title}</p>
              <p className="truncate text-[13px] text-slate-500">
                <span dir="auto">{item.company}</span>{when && <> · {when}</>}
              </p>
            </div>
            <div className="min-w-[140px] flex-[0_1_180px]" role="img" aria-label={J.progress_label.replace('{n}', String(step + 1 || 0)).replace('{stage}', stage)}>
              <div className="grid grid-cols-4 gap-1" aria-hidden>
                {[0, 1, 2, 3].map(n => (
                  <span key={n} className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                    {n <= step && (
                      <span
                        className="block h-full origin-left rtl:origin-right animate-ja-grow bg-gradient-to-r rtl:bg-gradient-to-l from-teal-700 to-teal-500"
                        style={{ animationDelay: `${400 + Math.min(row, 8) * 80 + n * 120}ms` }}
                      />
                    )}
                  </span>
                ))}
              </div>
              <p className="mt-1.5 text-[12px] font-semibold" style={{ color: ink }} aria-hidden>{stage}</p>
            </div>
            <span className={`inline-flex h-8 shrink-0 items-center rounded-full px-3 text-[13px] font-medium ${NEXT_TONE[next]}`}>
              {J[`next_${next}`]}
            </span>
            {action(item)}
          </li>
        )
      })}
    </ol>
  )
}
