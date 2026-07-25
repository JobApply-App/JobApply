'use client'
import { useCallback, useEffect, useState } from 'react'
import { getGreetingName } from '@/lib/nameUtils'
import { TOKENS } from '@/lib/tokens'
import { getScoreBand } from '@/lib/scoreBand'
import type { ApiFeedJob, ScoreBreakdown } from '@/lib/apiTypes'
import { Skeleton } from './ui/Skeleton'
import { SparkIcon, UserBadgeIcon, FileIcon, SlidersIcon, ArrowIcon, SearchIcon, BoltIcon, CheckIcon } from './icons'
import { TrustDashboard } from './TrustDashboard'
import { useChat } from '@/contexts/ChatContext'
import {
  fetchAnalyticsOverview, fetchScraperStatus, RateLimitError,
  type AnalyticsOverview, type ScraperStatus,
} from '@/lib/api'

// ── LinkedIn Scraper Status Banners ──────────────────────────────────────────
//
// BLOCKED — enrichment loop auto-paused after ≥ 2 redirect-loop errors
//           (ERR_TOO_MANY_REDIRECTS = LinkedIn bot-detection signal).
// PAUSED  — manually paused via reset_linkedin_scraper.py --pause while a
//            fresh li_at cookie is being configured.  Not an error state.

function LinkedInBlockedBanner({ blockedAt }: { blockedAt: string | null }) {
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
          LinkedIn Connection Blocked
        </p>
        <p className="text-[12px] text-slate-600 leading-relaxed">
          The scraper hit a redirect loop (bot-detection) and has been paused to protect your
          IP.{formattedAt && <> Blocked at {formattedAt}.</>}
          {' '}Run{' '}
          <code className="font-mono text-[11px]">venv/bin/python -m backend.scripts.reset_linkedin_scraper --pause</code>
          , update <code className="font-mono text-[11px]">LINKEDIN_LI_AT</code> in{' '}
          <code className="font-mono text-[11px]">backend/.env</code>, then run{' '}
          <code className="font-mono text-[11px]">--resume</code>.
        </p>
      </div>
    </div>
  )
}

function LinkedInPausedBanner() {
  return (
    <div
      className="rounded-xl px-4 py-3.5 flex items-start gap-3"
      style={{ background: 'oklch(0.97 0.04 55)', border: '1px solid oklch(0.90 0.06 55)' }}
      role="status"
    >
      <span className="text-[18px] shrink-0 mt-0.5" aria-hidden="true">⏸</span>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-bold text-slate-800 mb-0.5">
          LinkedIn Scraper Maintenance Pause
        </p>
        <p className="text-[12px] text-slate-600 leading-relaxed">
          The enrichment loop is paused while a fresh cookie is being configured.
          Update <code className="font-mono text-[11px]">LINKEDIN_LI_AT</code> in{' '}
          <code className="font-mono text-[11px]">backend/.env</code>, then run{' '}
          <code className="font-mono text-[11px]">venv/bin/python -m backend.scripts.reset_linkedin_scraper --resume</code>{' '}
          to restart scraping.
        </p>
      </div>
    </div>
  )
}

// ── KPI cards ─────────────────────────────────────────────────────────────────
// Premium metric cards: soft-shadow surface, tinted icon chip, an accent glow
// that intensifies on hover, and a large accent-coloured number so each metric
// carries its own visual identity and "pops" off the canvas.

type KPIIcon = (props: { s?: number }) => JSX.Element

function KPIStat({ label, value, sub, accent, Icon }: {
  label: string; value: string | number; sub: string; accent: string; Icon: KPIIcon
}) {
  return (
    <div
      className="group relative overflow-hidden rounded-2xl bg-white border border-slate-100 px-5 pt-5 pb-6 transition-all duration-300 ease-out hover:-translate-y-0.5"
      style={{ boxShadow: TOKENS.shadow.card }}
    >
      {/* Soft accent glow, top-right — brightens on hover for a tactile feel */}
      <span
        aria-hidden
        className="pointer-events-none absolute -top-10 -right-10 h-28 w-28 rounded-full blur-2xl opacity-[0.08] transition-opacity duration-300 group-hover:opacity-[0.16]"
        style={{ background: accent }}
      />
      {/* Icon chip */}
      <span
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-xl mb-4 transition-transform duration-300 group-hover:scale-105"
        style={{ background: `color-mix(in oklab, ${accent} 12%, white)`, color: accent }}
      >
        <Icon s={17} />
      </span>
      {/* Big accent-coloured value */}
      <span
        className="relative block text-[36px] font-bold leading-none tracking-tight"
        style={{ color: accent, fontVariantNumeric: 'tabular-nums' }}
      >
        {value}
      </span>
      {/* Label + sub */}
      <span className="relative mt-3 block text-[11px] font-semibold uppercase tracking-[0.11em] text-slate-500">
        {label}
      </span>
      <span className="relative mt-1 block text-[12px] text-slate-400 leading-snug">
        {sub}
      </span>
    </div>
  )
}

// Daily activity strip: the two "today" counters reset at UTC midnight, with
// Average Match Score on the right as the stable quality signal. Order is
// fixed left→right: Jobs Scanned Today · Actions Taken Today · Avg Match Score.
function KPIRow({ jobsScannedToday, actionsTakenToday, averageMatchScore, loading }: {
  jobsScannedToday:  number
  actionsTakenToday: number
  averageMatchScore: number
  loading:           boolean
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        {[0, 1, 2].map(i => (
          <div
            key={i}
            className="rounded-2xl bg-white border border-slate-100 px-5 pt-5 pb-6"
            style={{ boxShadow: TOKENS.shadow.card }}
          >
            <Skeleton className="h-9 w-9 rounded-xl mb-4" />
            <Skeleton className="h-9 w-20" />
            <Skeleton className="h-2.5 w-24 mt-3" />
            <Skeleton className="h-2.5 w-32 mt-2" />
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
      <KPIStat
        label="Jobs scanned today"
        value={jobsScannedToday}
        sub="New roles surfaced since midnight"
        accent={TOKENS.color.primary}
        Icon={SearchIcon}
      />
      <KPIStat
        label="Actions taken today"
        value={actionsTakenToday}
        sub="Applications you submitted today"
        accent={TOKENS.color.success}
        Icon={BoltIcon}
      />
      <KPIStat
        label="Average match score"
        value={`${averageMatchScore.toFixed(1)}%`}
        sub="ATS fit across your scored jobs"
        accent={TOKENS.color.primaryHover}
        Icon={SparkIcon}
      />
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
  return (
    <div
      className="rounded-xl px-4 py-3 flex items-center gap-3"
      style={{ background: 'oklch(0.97 0.03 85)', border: '1px solid oklch(0.90 0.06 85)' }}
      role="alert"
    >
      <span className="text-[15px] shrink-0" aria-hidden="true">⚠️</span>
      <p className="flex-1 text-[12px] text-slate-600 leading-relaxed">
        {rateLimited
          ? 'Live analytics are briefly rate-limited. Please try again in a minute.'
          : 'Could not load live analytics right now.'}
      </p>
      <button
        onClick={onRetry}
        className="shrink-0 text-[12px] font-semibold text-slate-600 hover:text-slate-900 underline underline-offset-2 transition-colors"
      >
        Retry
      </button>
    </div>
  )
}

// ── Quick actions ─────────────────────────────────────────────────────────────
// A 2×2 grid of interactive action cards — each with a distinct icon container,
// an accent hairline that grows on hover, and a soft lift. Strictly teal/emerald.

function QuickActions({ newCount, savedCount, onGo }: {
  newCount: number; savedCount: number; onGo: (tab: string) => void
}) {
  const items = [
    {
      id: 'review', tab: 'feed',
      label: `Review ${newCount} new matches`,
      sub: 'Top matches this morning',
      accent: TOKENS.color.primary,
      Icon: SparkIcon,
    },
    {
      id: 'profile', tab: 'profile-builder:optimize_gaps',
      label: 'Strengthen your profile',
      sub: 'Targets low-confidence claims first',
      accent: TOKENS.color.success,
      Icon: UserBadgeIcon,
    },
    {
      id: 'cv', tab: 'profile-builder',
      label: 'Update your CV',
      sub: 'Open the AI Profile Builder',
      accent: TOKENS.color.primaryHover,
      Icon: FileIcon,
    },
    {
      id: 'prefs', tab: 'prefs',
      label: 'Tune your preferences',
      sub: 'Match score, work mode, location',
      accent: TOKENS.color.success,
      Icon: SlidersIcon,
    },
  ]

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.12em] text-slate-400">
          Quick actions
        </h2>
      </div>
      {/* flex-1 lets the 2×2 grid absorb the column's remaining height; the
          sm:grid-rows-2 template splits that height into two equal fr rows so
          the cards stretch to meet the 4-row Top Matches stack at the bottom. */}
      <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 sm:grid-rows-2 gap-3">
        {items.map(it => {
          const { Icon } = it
          return (
            <button
              key={it.id}
              onClick={() => onGo(it.tab)}
              className="group text-left rounded-2xl bg-white border border-slate-100 p-5 transition-all duration-200 ease-out hover:border-slate-200 hover:-translate-y-px shadow-[0_1px_3px_rgba(15,23,42,0.06),0_1px_2px_rgba(15,23,42,0.04)] hover:shadow-[0_4px_12px_rgba(15,23,42,0.07),0_2px_4px_rgba(15,23,42,0.04)]"
            >
              <div className="flex items-start gap-3.5">
                <span
                  className="inline-flex h-9 w-9 items-center justify-center rounded-xl shrink-0"
                  style={{
                    background: `color-mix(in oklab, ${it.accent} 10%, white)`,
                    color: it.accent,
                  }}
                >
                  <Icon s={15} />
                </span>
                <span className="flex-1 min-w-0 pt-0.5">
                  <span className="flex items-center gap-1.5">
                    <span className="block text-[13.5px] font-semibold text-slate-800 leading-snug">
                      {it.label}
                    </span>
                    <span className="text-slate-300 -translate-x-1 opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100 group-hover:text-slate-400">
                      <ArrowIcon s={12} />
                    </span>
                  </span>
                  <span className="block text-[12px] text-slate-400 mt-1.5 leading-snug">{it.sub}</span>
                </span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Top match row ─────────────────────────────────────────────────────────────
// A lightweight read-only row — NOT a full JobCard accordion.
// Clicking navigates the user to the Matches tab rather than expanding in-place.

// Score badge — a filled, tinted square so the match score reads as a
// deliberate metric chip rather than loose text. Brand teal/emerald only.
function ScorePip({ score }: { score: number }) {
  const band = getScoreBand(score)

  return (
    <div className={`flex flex-col items-center justify-center shrink-0 rounded-xl h-11 w-11 border border-slate-100 ${band.bg}`}>
      <span className={`text-[13px] font-bold tabular-nums leading-none ${band.text}`}>
        {score.toFixed(1)}
      </span>
      <span className="text-[8px] font-semibold uppercase tracking-wide mt-0.5 text-slate-400">
        ATS
      </span>
    </div>
  )
}

function TopMatchRow({ job, onClick }: { job: ApiFeedJob; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group w-full text-left flex items-center gap-3.5 rounded-2xl bg-white border border-slate-100 px-4 py-3.5 mb-2.5 transition-all duration-200 ease-out hover:border-slate-200 hover:-translate-y-px shadow-[0_1px_3px_rgba(15,23,42,0.06),0_1px_2px_rgba(15,23,42,0.04)] hover:shadow-[0_4px_12px_rgba(15,23,42,0.07),0_2px_4px_rgba(15,23,42,0.04)]"
    >
      <ScorePip score={job.match_score} />

      <div className="flex-1 min-w-0">
        <p className="text-[13.5px] font-semibold text-slate-900 truncate leading-snug">
          {job.title}
        </p>
        <p className="text-[12px] text-slate-500 truncate mt-0.5">
          {job.company}
          {job.location && (
            <span className="text-slate-300 mx-1.5">·</span>
          )}
          {job.location}
        </p>
        {/* Reasons as understated editorial text — no pills, no tinted fills */}
        {job.reasons.length > 0 && (
          <p className="text-[11px] text-slate-400 mt-1.5 truncate">
            {job.reasons.slice(0, 2).map(r => r.label).join('  ·  ')}
          </p>
        )}
      </div>

      <span className="shrink-0 text-slate-300 transition-all duration-200 group-hover:translate-x-0.5 group-hover:text-slate-400">
        <ArrowIcon s={14} />
      </span>
    </button>
  )
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function TopMatchSkeleton({ opacity }: { opacity: number }) {
  return (
    <div
      className="flex items-center gap-3.5 rounded-2xl bg-white border border-slate-100 px-4 py-3.5 mb-2.5"
      style={{ opacity, boxShadow: TOKENS.shadow.card }}
    >
      <Skeleton className="h-11 w-11 rounded-xl shrink-0" />
      <div className="flex-1 space-y-1.5">
        <Skeleton className="h-3.5 w-48" />
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-2.5 w-40" />
      </div>
    </div>
  )
}

// ── System Confidence Score — gamified Ariel engagement hook ────────────────
// Score is the backend's overall_trust_score (ProfileUpdateService.compute_
// profile_trust_score), mirrored down from <TrustDashboard onScoreChange>
// so this card doesn't fire its own duplicate /trust-score request.

// Gamified engagement copy stays encouraging even at low scores, but the
// underlying threshold and color always come from the shared Meridian V2
// score band (§2.3) — never a separate ad hoc scale.
const CONFIDENCE_TIER_LABEL: Record<ReturnType<typeof getScoreBand>['key'], string> = {
  exceptional: 'Excellent',
  strong:      'Strong',
  moderate:    'Building',
  weak:        'Getting started',
  poor:        'Just started',
}

function confidenceTier(pct: number): { label: string; color: string } {
  const band = getScoreBand(pct)
  return { label: CONFIDENCE_TIER_LABEL[band.key], color: band.hexFg }
}

function ConfidenceGauge({ pct, color }: { pct: number | null; color: string }) {
  const SIZE = 76
  const RADIUS = 30
  const CIRCUMFERENCE = 2 * Math.PI * RADIUS
  const dash = pct !== null ? (Math.min(100, Math.max(0, pct)) / 100) * CIRCUMFERENCE : 0

  return (
    <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
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
const PILLAR_META = [
  {
    key:   'breadth' as const,
    label: 'Breadth',
    max:   40,
    color: TOKENS.color.primary,     // #0D9488 teal-600
    Icon:  SearchIcon,
    caption: 'Volume of parsed data',
    hint:  'Breadth — how much of your professional landscape the system has '
         + 'extracted from CVs and chats. More data means a more complete picture.',
  },
  {
    key:   'depth' as const,
    label: 'Depth',
    max:   40,
    color: TOKENS.color.success,     // #059669 emerald-600
    Icon:  CheckIcon,
    caption: 'Verified & accurate claims',
    hint:  'Depth — claims you have verified or clarified (tests, STAR probes, '
         + 'honest proficiency levels). This is the main path toward 100%.',
  },
  {
    key:   'context' as const,
    label: 'Context',
    max:   20,
    color: '#2DD4BF',                // teal-400
    Icon:  UserBadgeIcon,
    caption: 'Profile basics & interaction',
    hint:  'Context — profile completeness (name, contact, goals) plus how much '
         + 'you have engaged with Ariel. Small but steady wins.',
  },
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
  Icon:    ({ s }: { s?: number }) => JSX.Element
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
          <span className="text-[11px] font-bold tabular-nums text-slate-900">
            {Math.round(value)}
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

function ConfidenceScoreCard({ score, breakdown, onImprove }: {
  score:      number | null
  breakdown:  ScoreBreakdown | null
  onImprove:  () => void
}) {
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
        <ConfidenceGauge pct={pct} color={tier?.color ?? TOKENS.color.primary} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <h2 className="text-[13.5px] font-bold text-slate-900 tracking-tight">
              System Confidence Score
            </h2>
            {tier && (
              <span
                className="inline-flex items-center h-[18px] px-2 rounded-md text-[10.5px] font-semibold"
                style={{ background: `color-mix(in oklab, ${tier.color} 12%, white)`, color: tier.color }}
              >
                {tier.label}
              </span>
            )}
          </div>
          <p className="text-[12px] text-slate-500 leading-relaxed">
            How well the system knows your profile — built from three pillars.
            Verify your claims and share more to grow it.
          </p>
        </div>

        <button
          onClick={onImprove}
          className="hidden sm:inline-flex items-center gap-1.5 h-8 px-3.5 rounded-lg text-[12.5px] font-semibold transition active:scale-[0.97] hover:opacity-90 shrink-0"
          style={{ background: TOKENS.color.primary, color: '#fff' }}
        >
          <SparkIcon s={12} />
          Improve with Ariel
        </button>
      </div>

      {/* ── Composition bar: the three pillars stacked toward 100 ──────── */}
      <div
        className="mt-4 flex h-2 w-full rounded-full overflow-hidden"
        style={{ background: TOKENS.color.lineSoft }}
        title="Your score is the sum of Breadth, Depth and Context (max 100)."
      >
        {breakdown && PILLAR_META.map(p => (
          <div
            key={p.key}
            className="h-full first:rounded-l-full"
            style={{
              width: `${Math.min(100, Math.max(0, breakdown[p.key]))}%`,
              background: p.color,
              transition: 'width 700ms cubic-bezier(0.22,1,0.36,1)',
            }}
          />
        ))}
      </div>

      {/* ── Three pillar rails with tooltips + micro-copy ──────────────── */}
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-x-5 gap-y-4">
        {PILLAR_META.map(p => (
          <PillarRail
            key={p.key}
            label={p.label}
            value={breakdown ? breakdown[p.key] : null}
            max={p.max}
            color={p.color}
            Icon={p.Icon}
            caption={p.caption}
            hint={p.hint}
            loading={loading}
          />
        ))}
      </div>

      {/* ── Mobile CTA (header CTA is hidden on narrow screens) ─────────── */}
      <button
        onClick={onImprove}
        className="sm:hidden mt-4 w-full inline-flex items-center justify-center gap-1.5 h-9 px-3.5 rounded-lg text-[12.5px] font-semibold transition active:scale-[0.98]"
        style={{ background: TOKENS.color.primary, color: '#fff' }}
      >
        <SparkIcon s={12} />
        Improve with Ariel
      </button>
    </section>
  )
}

// ── Greeting helpers ───────────────────────────────────────────────────────────

function _timeGreeting(): string {
  const h = new Date().getHours()
  if (h >= 5  && h < 12) return 'Good morning'
  if (h >= 12 && h < 17) return 'Good afternoon'
  if (h >= 17 && h < 21) return 'Good evening'
  return 'Good night'
}

// e.g. "Tuesday, 7 July" — used in the header date pill for a live, welcoming feel.
function _todayLabel(): string {
  return new Date().toLocaleDateString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long',
  })
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface OverviewProps {
  userId:           string
  jobsScannedToday: number
  feedJobs:         ApiFeedJob[]
  jobsLoading:      boolean
  savedIds:         string[]
  displayName?:     string
  onSave:     (id: string) => void
  onReviewCV: (id: string) => void
  onGo:       (tab: string, jobId?: string) => void
}

// ── Overview ──────────────────────────────────────────────────────────────────

export function Overview({
  userId, jobsScannedToday, feedJobs, jobsLoading, savedIds, displayName,
  onSave, onReviewCV, onGo,
}: OverviewProps) {
  const previewJobs = feedJobs.slice(0, 4)

  // ── System Confidence Score (Phase 14) ──────────────────────────────────────
  // Mirrored from TrustDashboard's own /trust-score fetch via onScoreChange —
  // see the comment above ConfidenceScoreCard for why we don't fetch it twice.
  const { openChat, profileVersion } = useChat()
  const [confidenceScore, setConfidenceScore] = useState<number | null>(null)
  const [scoreBreakdown, setScoreBreakdown]   = useState<ScoreBreakdown | null>(null)

  // Mirror both the overall score and its three-pillar breakdown up from
  // TrustDashboard's single /trust-score fetch (Phase 32).
  const handleScoreChange = useCallback((score: number, breakdown?: ScoreBreakdown) => {
    setConfidenceScore(score)
    if (breakdown) setScoreBreakdown(breakdown)
  }, [])

  const handleImproveScore = useCallback(() => {
    openChat({
      topic: 'I want to improve my System Confidence Score by sharing more details '
        + 'about my experience so my job matches and CV tailoring get more accurate.',
    })
  }, [openChat])

  // ── Server-side analytics (Phase 6) ─────────────────────────────────────────
  // fetchAnalyticsOverview() awaits ensureFreshToken() before attaching auth
  // headers, so the mount-time empty-token race cannot 401 this request.
  const [overview,        setOverview]        = useState<AnalyticsOverview | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewError,   setOverviewError]   = useState<'rate_limited' | 'failed' | null>(null)

  const loadOverview = useCallback(() => {
    let cancelled = false
    setOverviewLoading(true)
    fetchAnalyticsOverview()
      .then(d => {
        if (cancelled) return
        setOverview(d)
        setOverviewError(null)
      })
      .catch(err => {
        if (cancelled) return
        setOverviewError(err instanceof RateLimitError ? 'rate_limited' : 'failed')
      })
      .finally(() => { if (!cancelled) setOverviewLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => loadOverview(), [loadOverview])

  // KPIs come EXCLUSIVELY from the analytics API (real per-user DB counts).
  // No client-derived or mock fallbacks: when the API has no data (or fails),
  // the honest answer is 0. The two "today" counters are UTC-midnight scoped
  // server-side, so they reflect only today's activity.
  const kpiJobsScannedToday  = overview?.jobs_scanned_today  ?? 0
  const kpiActionsTakenToday = overview?.actions_taken_today ?? 0
  const kpiAverageMatchScore = overview?.average_match_score ?? 0
  const kpiLoading           = overviewLoading

  const handleMatchClick    = useCallback(()              => onGo('feed'),         [onGo])
  const handleMatchJobClick = useCallback((jobId: string) => onGo('feed', jobId),  [onGo])

  // ── LinkedIn scraper status — polled on mount + every 30 s ─────────────────
  // Re-polling is necessary because the Overview component stays mounted even
  // while the user is on other tabs, and the reset script can change the KV
  // state at any time.  A stale in-memory snapshot would keep the BLOCKED
  // banner visible long after the status was cleared.
  const [scraperStatus, setScraperStatus] = useState<ScraperStatus | null>(null)
  useEffect(() => {
    let cancelled = false
    const poll = () => {
      fetchScraperStatus()
        .then(s => { if (!cancelled) setScraperStatus(s) })
        .catch(() => { /* non-critical — ignore */ })
    }
    poll()
    const interval = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  return (
    <div className="space-y-10">

      {/* ── LinkedIn scraper status banners ──────────────────────────────── */}
      {scraperStatus?.status === 'BLOCKED' && (
        <LinkedInBlockedBanner blockedAt={scraperStatus.blocked_at} />
      )}
      {scraperStatus?.status === 'PAUSED' && (
        <LinkedInPausedBanner />
      )}

      {/* ── Hero greeting ───────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[34px] font-bold text-slate-900 tracking-[-0.02em] leading-[1.1]">
            {_timeGreeting()}
            {getGreetingName(displayName ?? '') && (
              <>
                ,{' '}
                <span style={{ color: TOKENS.color.primary }}>
                  {getGreetingName(displayName ?? '')}
                </span>
              </>
            )}
          </h1>
          <p className="text-[14.5px] text-slate-400 mt-2">
            Here&apos;s what happened overnight.
          </p>
        </div>

        {/* Live date pill — grounds the dashboard as a fresh daily snapshot */}
        <span
          className="inline-flex items-center gap-2 h-9 px-3.5 rounded-full bg-white border border-slate-100 text-[12.5px] font-medium text-slate-500 shrink-0"
          style={{ boxShadow: TOKENS.shadow.card }}
        >
          <span
            className="block h-1.5 w-1.5 rounded-full"
            style={{ background: TOKENS.color.primary }}
          />
          {_todayLabel()}
        </span>
      </div>

      {/* ── System Confidence Score — gamified Ariel engagement CTA ──────── */}
      <ConfidenceScoreCard
        score={confidenceScore}
        breakdown={scoreBreakdown}
        onImprove={handleImproveScore}
      />

      {/* ── KPI strip — server analytics with local fallback ─────────────── */}
      <section className="space-y-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Today at a glance
        </h2>
        {overviewError && !overviewLoading && (
          <AnalyticsErrorBanner
            rateLimited={overviewError === 'rate_limited'}
            onRetry={loadOverview}
          />
        )}
        <KPIRow
          jobsScannedToday={kpiJobsScannedToday}
          actionsTakenToday={kpiActionsTakenToday}
          averageMatchScore={kpiAverageMatchScore}
          loading={kpiLoading}
        />
      </section>

      {/* ── Confidence Matrix (TrustDashboard) ──────────────────────────── */}
      {/* Wrapped in a premium surface so it blends with the KPI cards above. */}
      {/* Remounts on every tab-switch to Overview, so fetchData fires fresh. */}
      <section
        className="rounded-2xl bg-white border border-slate-100 p-6"
        style={{ boxShadow: TOKENS.shadow.card }}
      >
        <TrustDashboard userId={userId} onScoreChange={handleScoreChange} profileVersion={profileVersion} />
      </section>

      {/* ── Quick actions + Top matches, side by side on wide screens ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.1fr] gap-12 items-stretch">

        {/* Quick actions — h-full so its inner flex column can stretch to
            match the Top Matches list height in the adjacent grid cell. */}
        <section className="h-full">
          <QuickActions
            newCount={jobsScannedToday}
            savedCount={savedIds.length}
            onGo={onGo}
          />
        </section>

        {/* Top matches */}
        <section>
          <div className="flex items-baseline justify-between mb-4">
            <h2 className="text-[13px] font-semibold uppercase tracking-[0.12em] text-slate-400">
              Top matches today
            </h2>
            <button
              onClick={handleMatchClick}
              className="inline-flex items-center gap-1 text-[12px] text-slate-400 hover:text-slate-700 transition-colors"
            >
              See all <ArrowIcon s={11} />
            </button>
          </div>

          {jobsLoading ? (
            <>
              <TopMatchSkeleton opacity={1}   />
              <TopMatchSkeleton opacity={0.7} />
              <TopMatchSkeleton opacity={0.4} />
            </>
          ) : previewJobs.length > 0 ? (
            previewJobs.map(j => (
              <TopMatchRow
                key={j.job_id}
                job={j}
                onClick={() => handleMatchJobClick(j.job_id)}
              />
            ))
          ) : (
            <p className="py-8 text-[13px] text-slate-400">
              No matches yet. Your agents are scanning now.
            </p>
          )}
        </section>

      </div>
    </div>
  )
}
