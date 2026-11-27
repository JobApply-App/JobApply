'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { TOKENS } from '@/lib/tokens'
import { getScoreBand } from '@/lib/scoreBand'
import type { ApiFeedJob, ScoreBreakdown, TrustScoreResponse } from '@/lib/apiTypes'
import { Skeleton } from './ui/Skeleton'
import { buttonClasses } from './ui/Button'
import { SparkIcon, UserBadgeIcon, FileIcon, SlidersIcon, SearchIcon, CheckIcon } from './icons'
import { BriefHero, TodaySteps, TopMatchCards } from './home/MorningBrief'
import { strongCount } from '@/lib/morningBrief'
import { useNavCounts } from '@/hooks/useNavCounts'
import { ProductTour } from './ProductTour'
import { useChat } from '@/contexts/ChatContext'
import {
  streamDashboardOverview, fetchScraperStatus, fetchRolePreferences, fetchTrustScore, RateLimitError,
  type AnalyticsOverview, type ScraperStatus, type DashboardOverviewResponse,
} from '@/lib/api'
import { getLastKnownDashboardSnapshot, saveDashboardSnapshot, clearDashboardSnapshot } from '@/lib/dashboardLocalCache'
import {
  diffScore, loadSnapshot, saveSnapshot, missingAnchors,
  type ScoreChange, type ScoreSnapshot,
} from '@/lib/scoreChange'

// ── LinkedIn Scraper Status Banners ──────────────────────────────────────────
//
// BLOCKED — enrichment loop auto-paused after ≥ 2 redirect-loop errors
//           (ERR_TOO_MANY_REDIRECTS = LinkedIn bot-detection signal).
// PAUSED  — manually paused via reset_linkedin_scraper.py --pause while a
//            fresh li_at cookie is being configured.  Not an error state.

// The operator's fix-it steps (server commands, .env keys) are for development;
// a user only needs to know LinkedIn jobs are paused.
const IS_DEV = process.env.NODE_ENV === 'development'

function LinkedInBlockedBanner({ blockedAt }: { blockedAt: string | null }) {
  const O = useI18n().t.overview
  const formattedAt = blockedAt
    ? new Date(blockedAt).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
    : null

  return (
    <div
      className="rounded-xl px-4 py-3.5 flex items-start gap-3"
      style={{ background: 'oklch(0.97 0.04 25)', border: '1px solid oklch(0.88 0.08 25)' }}
      role="alert"
    >
      <span className="text-[18px] shrink-0 mt-0.5" aria-hidden="true">🚫</span>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-bold text-slate-800 mb-0.5">
          {O.linkedin_blocked}
        </p>
        <p className="text-[12px] text-slate-600 leading-relaxed">
          {O.linkedin_blocked_body}
          {IS_DEV && <>
            {' '}The scraper hit a redirect loop (bot-detection) and has been paused to protect your
            IP.{formattedAt && <> Blocked at {formattedAt}.</>}
            {' '}Run{' '}
            <code className="font-mono text-[11px]">venv/bin/python -m backend.scripts.reset_linkedin_scraper --pause</code>
            , update <code className="font-mono text-[11px]">LINKEDIN_LI_AT</code> in{' '}
            <code className="font-mono text-[11px]">backend/.env</code>, then run{' '}
            <code className="font-mono text-[11px]">--resume</code>.
          </>}
        </p>
      </div>
    </div>
  )
}

// ── What blocks matching ─────────────────────────────────────────────────────
// Without saved roles or a readable CV the user gets no automatic matches at
// all (the old fallback to a general list fed them someone else's roles), so
// when one of those is missing it is the only step shown. One ask, in the
// app, instead of sending people back through onboarding on each sign-in.
// Otherwise the morning brief's steps for today take this place.

function useBlockingStep(entityCount: number | null, onGo: (tab: string) => void) {
  const O = useI18n().t.overview
  const [rolesMissing, setRolesMissing] = useState(false)
  const [cvUnreadable, setCvUnreadable] = useState(false)
  useEffect(() => {
    let cancelled = false
    fetchRolePreferences()
      .then(({ roles, cvUnreadable }) => {
        if (cancelled) return
        setRolesMissing(roles.length === 0)
        setCvUnreadable(cvUnreadable)
      })
      .catch(() => { /* unknown: don't nag */ })
    return () => { cancelled = true }
  }, [])

  // Priority: a CV saved with no work experience (uploads from before
  // 2026-10-16 that the model failed to read were stored empty) comes first,
  // since uploading it again fixes matching for good; then roles, which
  // decide which jobs reach the user at all; then the CV they are scored
  // against.
  let step: BlockingStep | null = null
  if (cvUnreadable) {
    step = { title: O.cv_unreadable_title, body: O.cv_unreadable_body, cta: O.cv_unreadable_cta,
             act: () => onGo('profile-builder'), warn: true }
  } else if (rolesMissing) {
    step = { title: O.roles_missing_title, body: O.roles_missing_body, cta: O.roles_missing_cta,
             act: () => { window.location.href = '/onboarding?step=preferences' } }
  } else if (entityCount === 0) {
    step = { ...O.next.cv, act: () => onGo('profile-builder') }
  }
  if (step && cvUnreadable && rolesMissing) step.alsoRoles = true
  return step
}

interface BlockingStep { title: string; body: string; cta: string; act: () => void; warn?: boolean; alsoRoles?: boolean }

function BlockingStepCard({ step }: { step: BlockingStep }) {
  const O = useI18n().t.overview
  return (
    <section
      aria-label={O.next_step_label}
      className={`animate-ja-reveal rounded-[24px] p-6 sm:p-7 flex flex-col sm:flex-row sm:items-center gap-5 border shadow-elevation-2 ${
        step.warn ? 'border-amber-200 bg-amber-50' : 'border-teal-100 bg-white'}`}
      style={{ animationDelay: '380ms' }}
    >
      <div className="flex-1 min-w-0">
        <h2 className="text-[22px] sm:text-[24px] font-extrabold tracking-[-0.03em] text-slate-900">{step.title}</h2>
        <p className="mt-1.5 text-[15px] text-slate-600 leading-relaxed">{step.body}</p>
      </div>
      <div className="shrink-0 flex flex-col sm:items-end gap-1.5">
        <button onClick={step.act} className={buttonClasses({ variant: 'primary', size: 'lg' })}>
          {step.cta}
        </button>
        {step.alsoRoles && (
          <a href="/onboarding?step=preferences" className="text-[14px] font-semibold text-teal-800 underline text-center py-1">
            {O.cv_unreadable_roles}
          </a>
        )}
      </div>
    </section>
  )
}

function LinkedInPausedBanner() {
  const O = useI18n().t.overview
  return (
    <div
      className="rounded-xl px-4 py-3.5 flex items-start gap-3"
      style={{ background: 'oklch(0.97 0.04 55)', border: '1px solid oklch(0.90 0.06 55)' }}
      role="status"
    >
      <span className="text-[18px] shrink-0 mt-0.5" aria-hidden="true">⏸</span>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-bold text-slate-800 mb-0.5">
          {O.linkedin_maintenance}
        </p>
        <p className="text-[12px] text-slate-600 leading-relaxed">
          {O.linkedin_paused_body}
          {IS_DEV && <>
            {' '}{O.linkedin_maintenance_body}
            {' '}Update <code className="font-mono text-[11px]">LINKEDIN_LI_AT</code> in{' '}
            <code className="font-mono text-[11px]">backend/.env</code>, then run{' '}
            <code className="font-mono text-[11px]">venv/bin/python -m backend.scripts.reset_linkedin_scraper --resume</code>{' '}
            to restart scraping.
          </>}
        </p>
      </div>
    </div>
  )
}

// ── Analytics error banner ────────────────────────────────────────────────────
// Shown when GET /api/analytics/overview fails; the KPI strip falls back to
// locally derived numbers so the dashboard stays useful.

function AnalyticsErrorBanner({ rateLimited, onRetry }: {
  rateLimited: boolean
  onRetry:     () => void
}) {
  const O = useI18n().t.overview
  const C = useI18n().t.common
  return (
    <div
      className="rounded-xl px-4 py-3 flex items-center gap-3"
      style={{ background: 'oklch(0.97 0.03 85)', border: '1px solid oklch(0.90 0.06 85)' }}
      role="alert"
    >
      <span className="text-[15px] shrink-0" aria-hidden="true">⚠️</span>
      <p className="flex-1 text-[12px] text-slate-600 leading-relaxed">
        {rateLimited
          ? O.analytics_rate_limited
          : O.analytics_failed}
      </p>
      <button
        onClick={onRetry}
        className="shrink-0 text-[12px] font-semibold text-slate-600 hover:text-slate-900 underline underline-offset-2 transition-colors"
      >
        {C.retry}
      </button>
    </div>
  )
}

// ── Quick actions ─────────────────────────────────────────────────────────────
// Secondary actions as one quiet row of links. They used to be four large
// cards competing with every other button on the page; the one action that
// matters now lives in NextStepCard.

function MoreActions({ onGo }: { onGo: (tab: string) => void }) {
  const O = useI18n().t.overview
  const items = [
    { id: 'profile', tab: 'profile-builder:optimize_gaps', label: O.qa_profile, Icon: UserBadgeIcon },
    { id: 'cv',      tab: 'profile-builder',               label: O.qa_cv,      Icon: FileIcon },
    { id: 'prefs',   tab: 'prefs',                         label: O.qa_prefs,   Icon: SlidersIcon },
  ]
  return (
    <nav aria-label={O.more_actions} className="flex flex-wrap items-center gap-x-5 gap-y-2">
      <span className="text-[14px] text-slate-500">{O.more_actions}</span>
      {items.map(({ id, tab, label, Icon }) => (
        <button
          key={id}
          onClick={() => onGo(tab)}
          className="inline-flex items-center gap-1.5 min-h-[44px] sm:min-h-0 text-[13px] font-medium text-slate-600 hover:text-teal-700 transition-colors"
        >
          <Icon s={13} />{label}
        </button>
      ))}
    </nav>
  )
}

// ── Ariel strip ───────────────────────────────────────────────────────────────
// Testers did not know what Ariel was for — the only cue was an "Ask Ariel"
// button. One quiet line names her role, and three chips name concrete jobs
// she does; each opens her with that request already sent.

function ArielStrip() {
  const A = useI18n().t.ariel
  const { openChat } = useChat()
  return (
    <section
      aria-label={A.capabilities_title}
      data-tour="ariel"
      className="animate-ja-reveal flex flex-col sm:flex-row sm:items-center gap-4 rounded-[24px] border border-ja-ai/20 bg-white/70 px-5 py-5 sm:px-6 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_18px_40px_-28px_rgba(54,122,142,0.45)]"
      style={{ animationDelay: '820ms' }}
    >
      <span
        aria-hidden
        className="h-10 w-10 shrink-0 rounded-full"
        style={{ background: TOKENS.color.gradientIntelligence, boxShadow: '0 0 0 4px rgba(54,122,142,0.12)' }}
      />
      <p className="flex-1 min-w-0 text-[15px] text-slate-700 leading-snug">
        <span className="font-bold text-ja-aiInk">{A.name}</span>
        <span className="text-slate-400"> · </span>
        {A.tagline}
      </p>
      <div className="flex flex-wrap gap-2">
        {A.quick_actions.slice(0, 3).map(a => (
          <button
            key={a.label}
            onClick={() => openChat({ topic: a.prompt })}
            className={buttonClasses({ variant: 'ariel', size: 'sm' })}
          >
            {a.label}
          </button>
        ))}
      </div>
    </section>
  )
}

// ── System Confidence Score — gamified Ariel engagement hook ────────────────
// Score is the backend's overall_trust_score (ProfileUpdateService.compute_
// profile_trust_score), mirrored down from <TrustDashboard onScoreChange>
// so this card doesn't fire its own duplicate /trust-score request.

// Gamified engagement copy stays encouraging even at low scores, but the
// underlying threshold and color always come from the shared Meridian V2
// score band (§2.3) — never a separate ad hoc scale.

function confidenceTier(pct: number): { key: ReturnType<typeof getScoreBand>['key']; color: string } {
  const band = getScoreBand(pct)
  return { key: band.key, color: band.hexFg }
}

// 12 dots, evenly spaced, flying ~46px out of the gauge centre.
const BURST = Array.from({ length: 12 }, (_, i) => {
  const a = (i / 12) * Math.PI * 2
  return { dx: `${Math.round(Math.cos(a) * 46)}px`, dy: `${Math.round(Math.sin(a) * 46)}px`, i }
})

function ConfidenceGauge({ pct, color, celebrate = false }: {
  pct: number | null; color: string; celebrate?: boolean
}) {
  const SIZE = 76
  const RADIUS = 30
  const CIRCUMFERENCE = 2 * Math.PI * RADIUS
  const dash = pct !== null ? (Math.min(100, Math.max(0, pct)) / 100) * CIRCUMFERENCE : 0

  return (
    <div
      className="relative shrink-0"
      style={{ width: SIZE, height: SIZE, animation: celebrate ? 'ja-pop 600ms ease-out 1' : undefined }}
    >
      {celebrate && (
        <span aria-hidden="true" className="pointer-events-none absolute inset-0">
          {BURST.map(d => (
            <span
              key={d.i}
              className="absolute left-1/2 top-1/2 -ml-1 -mt-1 h-2 w-2 rounded-full"
              style={{
                background: d.i % 3 === 0 ? TOKENS.color.success : d.i % 3 === 1 ? color : '#F59E0B',
                animation: 'ja-burst 900ms cubic-bezier(0.22,1,0.36,1) forwards',
                ['--dx' as string]: d.dx, ['--dy' as string]: d.dy,
              } as React.CSSProperties}
            />
          ))}
        </span>
      )}
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke={TOKENS.color.lineSoft} strokeWidth={7} />
        {pct !== null && (
          <circle
            cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none"
            stroke={color} strokeWidth={7} strokeLinecap="round"
            strokeDasharray={`${dash} ${CIRCUMFERENCE}`}
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
            style={{ transition: 'stroke-dasharray 700ms cubic-bezier(0.22,1,0.36,1)' }}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        {pct === null ? (
          <Skeleton className="h-5 w-8 rounded" />
        ) : (
          <span className="text-[15px] font-bold tabular-nums" style={{ color }}>{pct.toFixed(1)}</span>
        )}
      </div>
    </div>
  )
}

// The three Holistic Familiarity pillars (Phase 32). Colours stay strictly
// inside the teal/emerald scales of the design system — no violet/purple.
//   Breadth  → teal-600 (brand primary)
//   Depth    → emerald-600 (success)
//   Context  → teal-400 (a lighter teal, distinct but on-brand)
// Label, caption and hint live in overview.pillars, looked up by `key`.
// Only the things that are not language stay here.
const PILLAR_META = [
  { key: 'breadth' as const, max: 40, color: TOKENS.color.primary, Icon: SearchIcon },
  { key: 'depth'   as const, max: 40, color: TOKENS.color.success, Icon: CheckIcon },
  { key: 'context' as const, max: 20, color: '#2DD4BF',            Icon: UserBadgeIcon },
]

// One elegant progress rail per pillar: icon + label + value/max + fill + copy.
// `loading` (the whole card is still fetching) drives the skeleton — NOT the
// presence of `value`. That distinction is the Phase 33 fix: a payload that
// arrives without a breakdown shows a muted "—", never an eternal skeleton.
function PillarRail({ label, value, max, color, Icon, caption, hint, loading }: {
  label:   string
  value:   number | null
  max:     number
  color:   string
  Icon:    ({ s }: { s?: number }) => React.JSX.Element
  caption: string
  hint:    string
  loading: boolean
}) {
  const pct = value !== null ? Math.min(100, Math.max(0, (value / max) * 100)) : 0
  return (
    <div className="min-w-0" title={hint}>
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-600">
          <span className="inline-flex" style={{ color }}><Icon s={12} /></span>
          {label}
        </span>
        {loading ? (
          <Skeleton className="h-3 w-8 rounded" />
        ) : value === null ? (
          <span className="text-[11px] font-medium text-slate-300">—</span>
        ) : (
          <span dir="ltr" className="text-[11px] font-bold tabular-nums text-slate-900">
            {value.toFixed(1)}
            <span className="text-slate-400 font-medium">/{max}</span>
          </span>
        )}
      </div>
      <div
        className="h-1.5 rounded-full overflow-hidden"
        style={{ background: TOKENS.color.lineSoft }}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${pct}%`,
            background: color,
            transition: 'width 700ms cubic-bezier(0.22,1,0.36,1)',
          }}
        />
      </div>
      <p className="mt-1 text-[10.5px] text-slate-400 leading-snug">{caption}</p>
    </div>
  )
}

function ConfidenceScoreCard({ score, breakdown, onImprove, change, chatSpan, liveDelta, onDismissChange }: {
  score:      number | null
  breakdown:  ScoreBreakdown | null
  onImprove:  () => void
  /** Difference from the last score this browser showed (null = nothing to say). */
  change:     ScoreChange | null
  /** Set when `change` summarises a whole chat with Ariel. */
  chatSpan:   { from: number; to: number } | null
  /** While a chat is open: running delta, shown quietly — no celebration per answer. */
  liveDelta:  number | null
  onDismissChange: () => void
}) {
  const O = useI18n().t.overview
  const SC = O.score_change
  const fmtDelta = (d: number) => `${d > 0 ? '+' : '−'}${Math.abs(d).toFixed(1)}`
  const missing = missingAnchors(breakdown?.identity ?? null)
  // 1-decimal precision throughout (.ai_rules) — no early rounding to an int.
  const pct  = score !== null ? Math.min(100, Math.max(0, score)) : null
  const tier = pct !== null ? confidenceTier(pct) : null
  // Loading is defined by the OVERALL score not yet being in — not by whether
  // the breakdown happens to be present. This keeps the pillars from being
  // trapped in a skeleton if a response ever omits score_breakdown.
  const loading = score === null

  return (
    <section
      className="rounded-2xl border border-slate-100 px-5 py-5"
      style={{ boxShadow: TOKENS.shadow.card }}
    >
      {/* ── Header row: gauge + title/description + CTA ─────────────────── */}
      <div className="flex items-center gap-5">
        <ConfidenceGauge
          pct={pct}
          color={tier?.color ?? TOKENS.color.primary}
          celebrate={change?.direction === 'up'}
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <h2 className="text-[13.5px] font-bold text-slate-900 tracking-tight">
              {O.confidence_title}
            </h2>
            {tier && (
              <span
                className="inline-flex items-center h-[18px] px-2 rounded-md text-[10.5px] font-semibold"
                style={{ background: `color-mix(in oklab, ${tier.color} 12%, white)`, color: tier.color }}
              >
                {O.bands[tier.key]}
              </span>
            )}
            {liveDelta !== null && Math.abs(liveDelta) >= 0.1 && (
              <span
                dir="ltr"
                className="inline-flex items-center h-[18px] px-2 rounded-md text-[10.5px] font-semibold tabular-nums"
                style={{
                  background: liveDelta > 0 ? 'oklch(0.96 0.04 160)' : 'oklch(0.96 0.04 70)',
                  color:      liveDelta > 0 ? 'oklch(0.45 0.12 160)' : 'oklch(0.48 0.12 60)',
                }}
                aria-live="polite"
              >
                {SC.live.replace('{delta}', fmtDelta(liveDelta))}
              </span>
            )}
          </div>
          <p className="text-[12px] text-slate-500 leading-relaxed">
            {O.confidence_body}
          </p>
        </div>

      </div>

      {/* ── What changed since last time (and why) ───────────────────────── */}
      {change && (change.direction === 'up' || change.direction === 'down') && (
        <div
          role="status"
          className="mt-4 rounded-xl px-4 py-3"
          style={change.direction === 'up'
            ? { background: 'oklch(0.97 0.03 160)', border: '1px solid oklch(0.90 0.05 160)' }
            : { background: 'oklch(0.98 0.03 75)',  border: '1px solid oklch(0.90 0.06 75)' }}
        >
          <div className="flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <p className="text-[12.5px] font-semibold text-slate-800">
                {chatSpan
                  ? (change.direction === 'up' ? SC.up_chat : SC.down_chat)
                      .replace('{from}', chatSpan.from.toFixed(1)).replace('{to}', chatSpan.to.toFixed(1))
                  : (change.direction === 'up' ? SC.up : SC.down).replace('{delta}', fmtDelta(change.delta))}
              </p>
              {change.direction === 'up' && (
                <p className="text-[12px] text-slate-600 mt-0.5">{SC.celebrate}</p>
              )}
              {change.reasons.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-[12px] text-slate-600 list-disc ps-4">
                  {change.reasons.map(r => <li key={r}>{SC.reasons[r]}</li>)}
                </ul>
              )}
              {change.direction === 'down' && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {change.reasons.includes('lost_roles') && (
                    <a
                      href="/onboarding?step=preferences"
                      className={buttonClasses({ variant: 'primary', size: 'sm' })}
                    >
                      {SC.fix_roles}
                    </a>
                  )}
                  <button
                    onClick={onImprove}
                    className={buttonClasses({ variant: 'ariel', size: 'sm' })}
                  >
                    <SparkIcon s={11} />{SC.ask_ariel}
                  </button>
                </div>
              )}
            </div>
            <button
              onClick={onDismissChange}
              className="shrink-0 text-[11.5px] font-medium text-slate-500 hover:text-slate-800"
            >
              {SC.dismiss}
            </button>
          </div>
        </div>
      )}

      {/* ── Three pillar rails with tooltips + micro-copy ──────────────── */}
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-x-5 gap-y-4">
        {PILLAR_META.map(p => (
          <PillarRail
            key={p.key}
            label={O.pillars[p.key].label}
            value={breakdown ? breakdown[p.key] : null}
            max={p.max}
            color={p.color}
            Icon={p.Icon}
            caption={O.pillars[p.key].caption}
            hint={O.pillars[p.key].hint}
            loading={loading}
          />
        ))}
      </div>

      {/* ── A concrete way up: what the score is still missing ──────────── */}
      {missing.length > 0 && (
        <p className="mt-4 text-[12px] text-slate-500">
          {O.missing_hint.replace('{items}', missing.map(k => O.missing_items[k]).join(', '))}
          {missing.includes('roles') && (
            <a href="/onboarding?step=preferences" className="ms-1.5 font-semibold text-teal-700 hover:text-teal-800">
              {SC.fix_roles}
            </a>
          )}
        </p>
      )}
    </section>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface OverviewProps {
  userId:           string
  jobsScannedToday: number
  feedJobs:         ApiFeedJob[]
  jobsLoading:      boolean
  savedIds:         string[]
  onSave:     (id: string) => void
  onReviewCV: (id: string) => void
  onGo:       (tab: string, jobId?: string) => void
}

// ── Overview ──────────────────────────────────────────────────────────────────

export function Overview({
  userId, jobsScannedToday, feedJobs, jobsLoading, savedIds,
  onSave, onReviewCV, onGo,
}: OverviewProps) {
  const { t } = useI18n()
  const O = t.overview
  // The jobs worth opening first: the feed's highest scores.
  const previewJobs = [...feedJobs].sort((a, b) => b.match_score - a.match_score).slice(0, 3)
  const strong      = strongCount(feedJobs)
  const navCounts   = useNavCounts()

  // ── System Confidence Score (Phase 14) ──────────────────────────────────────
  // Mirrored from TrustDashboard's own /trust-score fetch via onScoreChange —
  // see the comment above ConfidenceScoreCard for why we don't fetch it twice.
  const { openChat, profileVersion, isOpen: chatOpen } = useChat()
  const [confidenceScore, setConfidenceScore] = useState<number | null>(null)
  const [scoreBreakdown, setScoreBreakdown]   = useState<ScoreBreakdown | null>(null)

  // ── Score change: explain every move, celebrate a rise once ────────────────
  // Compared with the last score this browser showed. While Ariel's chat is
  // open the score can move after every answer; celebrating each one would be
  // noise, so it is shown as a quiet running delta and summarised (with one
  // celebration, if it rose) when the chat closes.
  const [scoreChange, setScoreChange] = useState<ScoreChange | null>(null)
  const [chatSpan,    setChatSpan]    = useState<{ from: number; to: number } | null>(null)
  const [liveDelta,   setLiveDelta]   = useState<number | null>(null)
  const chatStartRef = useRef<ScoreSnapshot | null>(null)
  const lastSnapRef  = useRef<ScoreSnapshot | null>(null)

  useEffect(() => {
    if (confidenceScore === null || !scoreBreakdown) return
    const snap: ScoreSnapshot = {
      overall: confidenceScore, breadth: scoreBreakdown.breadth, depth: scoreBreakdown.depth,
      context: scoreBreakdown.context, identity: scoreBreakdown.identity ?? null,
    }
    lastSnapRef.current = snap
    if (chatOpen) {
      if (!chatStartRef.current) chatStartRef.current = loadSnapshot(userId) ?? snap
      const d = Math.round((snap.overall - chatStartRef.current.overall) * 10) / 10
      setLiveDelta(d)
      return
    }
    const prev = loadSnapshot(userId)
    const change = diffScore(prev, snap)
    if (change.direction === 'up' || change.direction === 'down') {
      setScoreChange(change)
      setChatSpan(null)
    }
    saveSnapshot(userId, snap)
  }, [confidenceScore, scoreBreakdown, chatOpen, userId])

  // Chat closed: one summary of the whole conversation.
  useEffect(() => {
    if (chatOpen || !chatStartRef.current) return
    const start = chatStartRef.current
    const end   = lastSnapRef.current
    chatStartRef.current = null
    setLiveDelta(null)
    if (!end) return
    const change = diffScore(start, end)
    if (change.direction === 'up' || change.direction === 'down') {
      setScoreChange(change)
      setChatSpan({ from: start.overall, to: end.overall })
    }
    saveSnapshot(userId, end)
  }, [chatOpen, userId])

  // Mirror both the overall score and its three-pillar breakdown up from
  // TrustDashboard's single /trust-score fetch (Phase 32).
  const handleScoreChange = useCallback((score: number, breakdown?: ScoreBreakdown) => {
    setConfidenceScore(score)
    if (breakdown) setScoreBreakdown(breakdown)
  }, [])

  const handleImproveScore = useCallback(() => {
    openChat({
      topic: O.improve_score_topic,
    })
  }, [openChat, O.improve_score_topic])

  // ── Server-side analytics — progressive streaming ───────────────────────────
  // GET /api/dashboard/overview streams 4 independent sections as NDJSON —
  // each one updates its OWN widget's state (and clears that widget's OWN
  // loading flag) the instant it arrives, instead of the whole page waiting
  // for the slowest section. See backend/api/routes/dashboard.py's streaming
  // design — same one-connection, one-JOIN backend work as before, only
  // delivery changed from buffered to incremental. streamDashboardOverview()
  // awaits ensureFreshToken() before attaching auth headers, so the
  // mount-time empty-token race cannot 401 this request.
  //
  // Correctness-first design: the backend still has NO server-side cache —
  // every section is recomputed from the current committed database state on
  // every call. The ONLY thing cached anywhere is this component's
  // last-known-result snapshot, kept purely for instant first paint. It is
  // explicitly presented as such: `isShowingLastKnown` gates a
  // "Refreshing… as of <time>" label, cleared only once ALL 4 sections have
  // been confirmed fresh by this mount's stream — never left on, never
  // implied to be current data before that.
  const lastKnownSnapshot = getLastKnownDashboardSnapshot(userId)

  const [overview,        setOverview]        = useState<AnalyticsOverview | null>(
    () => lastKnownSnapshot?.data.overview ?? null
  )
  const [overviewLoading, setOverviewLoading] = useState(() => lastKnownSnapshot === null)
  const [overviewError,   setOverviewError]   = useState<'rate_limited' | 'failed' | null>(null)

  const [trustScoreData, setTrustScoreData] = useState<TrustScoreResponse | undefined>(
    () => lastKnownSnapshot?.data.trust_score
  )

  // The score card reads the trust score the stream brought (the radar that
  // used to relay it now lives on the Profile page), and asks for it again
  // when Ariel changes the profile mid-session.
  useEffect(() => {
    if (trustScoreData) handleScoreChange(trustScoreData.overall_trust_score ?? 0, trustScoreData.score_breakdown)
  }, [trustScoreData, handleScoreChange])

  const firstProfileVersion = useRef(profileVersion)
  useEffect(() => {
    if (!userId || profileVersion === firstProfileVersion.current) return
    let live = true
    fetchTrustScore(userId).then(d => { if (live) setTrustScoreData(d) }).catch(() => { /* the last score stays */ })
    return () => { live = false }
  }, [profileVersion, userId])

  // True until ALL 4 sections have been confirmed fresh by this mount's
  // stream — a page-level "Refreshing…" signal that sits ALONGSIDE (not
  // instead of) each widget's own independent loading/error state below.
  const [isShowingLastKnown, setIsShowingLastKnown] = useState(() => lastKnownSnapshot !== null)
  const [lastKnownAt,        setLastKnownAt]        = useState<string | null>(() => lastKnownSnapshot?.savedAt ?? null)

  const loadOverview = useCallback(() => {
    let cancelled = false
    if (lastKnownSnapshot === null) {
      setOverviewLoading(true)
    }
    setOverviewError(null)

    // Accumulates sections as they stream in; once all 4 have succeeded,
    // this mount's data is confirmed fresh (clears the last-known label)
    // and is saved as the new last-known snapshot for next visit's instant
    // paint. A section that errors never gets recorded here, so a partial
    // stream (some sections ok, one failed) never overwrites a good
    // previous snapshot with incomplete data.
    const collected: Partial<DashboardOverviewResponse> = {}
    const maybeFinish = () => {
      if (cancelled) return
      if (collected.overview && collected.scraper_status && collected.confidence_matrix && collected.trust_score) {
        setIsShowingLastKnown(false)
        setLastKnownAt(null)
        saveDashboardSnapshot(userId, collected as DashboardOverviewResponse)
      }
    }

    streamDashboardOverview(event => {
      if (cancelled) return
      if (event.section === 'overview') {
        if ('data' in event) {
          setOverview(event.data)
          setOverviewError(null)
          setOverviewLoading(false)
          collected.overview = event.data
          maybeFinish()
        } else {
          setOverviewError('failed')
          setOverviewLoading(false)
        }
      } else if (event.section === 'scraper_status') {
        if ('data' in event) {
          setScraperStatus(event.data)
          collected.scraper_status = event.data
          maybeFinish()
        }
        // Non-fatal on error, same as the 30s polling below — silently keep
        // whatever scraperStatus already had (last-known snapshot or null);
        // the banner is absent by default, so "no update yet" reads fine.
      } else if (event.section === 'confidence_matrix') {
        if ('data' in event) {
          collected.confidence_matrix = event.data
          maybeFinish()
        }
        // Kept only for the snapshot; the radar now lives on the Profile page.
      } else if (event.section === 'trust_score') {
        if ('data' in event) {
          setTrustScoreData(event.data)
          collected.trust_score = event.data
          maybeFinish()
        }
      }
    }).catch(err => {
      if (cancelled) return
      // Stream-level failure (network drop, non-200 before any lines
      // arrived) — surface it on the KPI row, the widget most directly
      // analogous to the page's overall health; sections that already
      // streamed in successfully before the drop keep showing their data.
      setOverviewError(err instanceof RateLimitError ? 'rate_limited' : 'failed')
      setOverviewLoading(false)
    })

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  useEffect(() => loadOverview(), [loadOverview])

  // Clear the PREVIOUS user's last-known snapshot on an actual user change
  // (userId prop switching to a different, non-empty value while this
  // component stays mounted) — belt-and-suspenders alongside
  // AuthContext.signOut()'s full localStorage.clear(). Deliberately NOT a
  // plain unmount cleanup: this component remounts on every tab-switch away
  // from Overview (see the TrustDashboard section comment below), and a
  // remount must NOT wipe the snapshot — that would defeat the entire
  // instant-render feature for the normal "switch tabs and come back" case.
  const previousUserIdRef = useRef(userId)
  useEffect(() => {
    const previousUserId = previousUserIdRef.current
    if (previousUserId && previousUserId !== userId) {
      clearDashboardSnapshot(previousUserId)
    }
    previousUserIdRef.current = userId
  }, [userId])

  // The average match comes only from the analytics API (a real per-user DB
  // figure); while it loads or after it fails the brief shows no number
  // rather than a made-up one.
  const averageMatch = overviewLoading || overviewError ? null : (overview?.average_match_score ?? null)

  const handleMatchClick    = useCallback(()              => onGo('feed'),         [onGo])
  const handleMatchJobClick = useCallback((jobId: string) => onGo('feed', jobId),  [onGo])
  const blockingStep = useBlockingStep(trustScoreData ? (trustScoreData.entities?.length ?? 0) : null, onGo)

  // ── LinkedIn scraper status — initial value from the aggregated fetch
  // above, then re-polled every 30 s ─────────────────────────────────────────
  // Re-polling (not the initial fetch — that's covered by loadOverview() now)
  // is necessary because the Overview component stays mounted even while the
  // user is on other tabs, and the reset script can change the KV state at
  // any time. A stale in-memory snapshot would keep the BLOCKED banner
  // visible long after the status was cleared.
  const [scraperStatus, setScraperStatus] = useState<ScraperStatus | null>(null)
  useEffect(() => {
    let cancelled = false
    const poll = () => {
      fetchScraperStatus()
        .then(s => { if (!cancelled) setScraperStatus(s) })
        .catch(() => { /* non-critical — ignore */ })
    }
    const interval = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  return (
    <div className="space-y-14 sm:space-y-16">

      {/* ── LinkedIn scraper status banners ──────────────────────────────── */}
      {scraperStatus?.status === 'BLOCKED' && (
        <LinkedInBlockedBanner blockedAt={scraperStatus.blocked_at} />
      )}
      {scraperStatus?.status === 'PAUSED' && (
        <LinkedInPausedBanner />
      )}

      {/* ── The morning brief: the sentence, the number, today's steps ──── */}
      <BriefHero
        strong={strong}
        fresh={jobsScannedToday}
        apps={navCounts.apps}
        avg={averageMatch}
        loading={jobsLoading}
        refreshing={isShowingLastKnown
          ? O.refreshing + (lastKnownAt ? ' ' + O.as_of.replace('{time}', new Date(lastKnownAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })) : '')
          : null}
        onReview={handleMatchClick}
        onAriel={handleImproveScore}
      />

      {overviewError && !overviewLoading && (
        <AnalyticsErrorBanner
          rateLimited={overviewError === 'rate_limited'}
          onRetry={loadOverview}
        />
      )}

      <ProductTour ready={!jobsLoading} />

      {blockingStep ? (
        <BlockingStepCard step={blockingStep} />
      ) : (
        <TodaySteps
          userId={userId}
          topJob={previewJobs[0] ?? null}
          hasMatches={feedJobs.length > 0}
          onReview={handleMatchClick}
          onTailor={onReviewCV}
          onAriel={handleImproveScore}
        />
      )}

      <TopMatchCards
        jobs={previewJobs}
        loading={jobsLoading}
        onOpen={handleMatchJobClick}
        onSeeAll={handleMatchClick}
      />

      {/* ── Ariel, in one line — what she is for, and a way straight in ── */}
      <ArielStrip />

      {/* ── System Confidence Score ─────────────────────────────────────── */}
      <div data-tour="confidence">
        <ConfidenceScoreCard
          score={confidenceScore}
          breakdown={scoreBreakdown}
          onImprove={handleImproveScore}
          change={scoreChange}
          chatSpan={chatSpan}
          liveDelta={chatOpen ? liveDelta : null}
          onDismissChange={() => { setScoreChange(null); setChatSpan(null) }}
        />
      </div>

      {/* ── Secondary actions, quietly ───────────────────────────────────── */}
      <MoreActions onGo={onGo} />
    </div>
  )
}
