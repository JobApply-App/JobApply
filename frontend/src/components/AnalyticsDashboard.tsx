'use client'

import { useEffect, useState } from 'react'
import { fetchAnalyticsSummary, type AnalyticsSummary } from '@/lib/api'
import { TOKENS } from '@/lib/tokens'

// ── Helpers ───────────────────────────────────────────────────────────────────

function barPct(val: number, max: number) {
  return max === 0 ? 0 : Math.min(100, Math.round((val / max) * 100))
}

// ── Stage config ──────────────────────────────────────────────────────────────
// Maps title-cased stage name → Tailwind bar class + hex label colour.
// Empty-state entries use the bar class too, but opacity-0 on the fill.

type StageConfig = { barClass: string; labelColor: string }

const STAGE_CONFIG: Record<string, StageConfig> = {
  'Submitted':    { barClass: 'bg-teal-500',   labelColor: '#0D9488' },
  'Phone Screen': { barClass: 'bg-sky-400',    labelColor: '#0284C7' },
  'Technical':    { barClass: 'bg-violet-500', labelColor: '#7C3AED' },
  'Interview':    { barClass: 'bg-amber-500',  labelColor: '#B45309' },
  'Offer':        { barClass: 'bg-emerald-500',labelColor: '#059669' },
  'Rejected':     { barClass: 'bg-rose-400',   labelColor: '#E11D48' },
}
const FALLBACK_CONFIG: StageConfig = {
  barClass:   'bg-slate-400',
  labelColor: '#475569',
}

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, accentColor,
}: {
  label:       string
  value:       string | number
  sub:         string
  accentColor: string
}) {
  return (
    <div
      className="flex-1 bg-white rounded-xl border border-slate-100 shadow-elevation-1 hover:shadow-elevation-2 transition-all duration-200"
      style={{ minWidth: 180, padding: '20px 24px 18px' }}
    >
      {/* Label row */}
      <div style={{ marginBottom: 10 }}>
        <p style={{
          fontSize: 10.5, fontWeight: 700, letterSpacing: '0.9px',
          textTransform: 'uppercase', color: TOKENS.color.muted,
          margin: 0,
        }}>
          {label}
        </p>
      </div>

      {/* Value */}
      <p style={{ fontSize: 32, fontWeight: 800, color: accentColor, lineHeight: 1, marginBottom: 6 }}>
        {value}
      </p>

      {/* Sub-label */}
      <p style={{ fontSize: 11.5, color: TOKENS.color.subtle, lineHeight: 1.45 }}>
        {sub}
      </p>
    </div>
  )
}

// ── Funnel Row ────────────────────────────────────────────────────────────────

function FunnelRow({
  stage, count, maxCount, isLast,
}: { stage: string; count: number; maxCount: number; isLast: boolean }) {
  const pct    = barPct(count, maxCount)
  const config = STAGE_CONFIG[stage] ?? FALLBACK_CONFIG
  const isEmpty = count === 0

  return (
    <div style={{ marginBottom: isLast ? 0 : 14 }}>
      {/* Stage label */}
      <span style={{
        display: 'block',
        fontSize: 12.5,
        fontWeight: isEmpty ? 400 : 600,
        color: isEmpty ? TOKENS.color.subtle : config.labelColor,
        marginBottom: 5,
      }}>
        {stage}
      </span>

      {/* Bar + count pill — vertically centered together */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* Progress rail */}
        <div className="h-2 rounded-full bg-slate-100 overflow-hidden" style={{ flex: 1 }}>
          {!isEmpty && (
            <div
              className={`h-full rounded-full ${config.barClass} transition-[width] duration-700 ease-out`}
              style={{ width: `${pct}%` }}
            />
          )}
        </div>
        {/* Count pill — centered with the bar */}
        <span
          className={isEmpty
            ? 'text-slate-400 bg-slate-100 rounded-full text-xs font-medium px-2 py-0.5 shrink-0'
            : 'text-slate-700 bg-slate-100 rounded-full text-xs font-bold px-2 py-0.5 shrink-0'}
        >
          {count}
        </span>
      </div>
    </div>
  )
}

// ── Keyword Tag ───────────────────────────────────────────────────────────────

function KeywordTag({ keyword, count }: { keyword: string; count: number }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-slate-700 bg-slate-50 border border-slate-200 rounded-lg text-xs font-medium whitespace-nowrap"
      style={{ padding: '5px 10px 5px 11px' }}
    >
      {keyword}
      <span className="bg-slate-200 text-slate-700 text-xs font-semibold px-2 py-0.5 rounded-full">
        {count}
      </span>
    </span>
  )
}

// ── Company Row ───────────────────────────────────────────────────────────────
//
// Horizontal bar row: company name on the left, bar proportional to count,
// and the count pill on the right.  maxCount drives the bar scale.

function CompanyRow({
  company, count, maxCount, isLast,
}: { company: string; count: number; maxCount: number; isLast: boolean }) {
  const pct = maxCount === 0 ? 0 : Math.min(100, Math.round((count / maxCount) * 100))

  return (
    <div style={{ marginBottom: isLast ? 0 : 12 }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 5,
      }}>
        <span style={{
          fontSize: 12.5, fontWeight: 600, color: TOKENS.color.ink,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          maxWidth: '75%',
        }}>
          {company}
        </span>
        <span className="text-slate-700 bg-slate-100 rounded-full text-xs font-bold px-2 py-0.5 shrink-0 ml-2">
          {count}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${pct}%`, background: TOKENS.color.primary }}
        />
      </div>
    </div>
  )
}

// ── Panel wrapper ─────────────────────────────────────────────────────────────

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="flex-1 bg-white rounded-xl border border-slate-100 shadow-elevation-1"
      style={{ minWidth: 300, padding: '22px 26px' }}
    >
      <p style={{
        fontSize: 10, fontWeight: 700, letterSpacing: '1.3px',
        textTransform: 'uppercase', color: TOKENS.color.primary,
        marginBottom: 18, paddingBottom: 12,
        borderBottom: `0.75px solid ${TOKENS.color.line}`,
      }}>
        {title}
      </p>
      {children}
    </div>
  )
}

// ── Empty hint (skills panel only) ────────────────────────────────────────────

function EmptyHint({ message }: { message: string }) {
  return (
    <p className="text-slate-400 text-sm italic text-center py-6">
      {message}
    </p>
  )
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, paddingBottom: 40 }}>
      {/* Title skeleton */}
      <div>
        <div className="h-6 w-48 bg-slate-100 rounded-lg animate-pulse mb-2" />
        <div className="h-4 w-64 bg-slate-100 rounded animate-pulse" />
      </div>
      {/* KPI skeleton */}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        {[1, 2, 3].map(i => (
          <div key={i} className="flex-1 bg-white rounded-xl border border-slate-100 shadow-elevation-1 animate-pulse"
            style={{ minWidth: 180, height: 110 }} />
        ))}
      </div>
      {/* Panel skeleton */}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        {[1, 2, 3].map(i => (
          <div key={i} className="flex-1 bg-white rounded-xl border border-slate-100 shadow-elevation-1 animate-pulse"
            style={{ minWidth: 260, height: 260 }} />
        ))}
      </div>
    </div>
  )
}


// ── Get Started Overlay ───────────────────────────────────────────────────────
//
// Shown when total_applications === 0. Guides the user to apply to their first
// 3 jobs so the funnel, rate, and company charts have meaningful data to render.

function GetStartedOverlay({ onGoToMatches }: { onGoToMatches?: () => void }) {
  return (
    <div
      className="rounded-2xl border border-slate-100 bg-white flex flex-col items-center justify-center text-center gap-5"
      style={{
        padding: '56px 40px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.04), 0 12px 32px rgba(0,0,0,0.04)',
      }}
    >
      <div
        className="flex items-center justify-center rounded-2xl"
        style={{ width: 64, height: 64, background: TOKENS.color.primarySoft }}
      >
        <span style={{ fontSize: 28 }} aria-hidden="true">📊</span>
      </div>

      <div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKENS.color.ink, margin: 0 }}>
          Your analytics will appear here
        </h2>
        <p style={{
          fontSize: 13.5, color: TOKENS.color.muted, marginTop: 8, lineHeight: 1.6, maxWidth: 360,
        }}>
          Apply to 3 jobs to see your interview rate, pipeline funnel, and top companies.
        </p>
      </div>

      {onGoToMatches && (
        <button
          onClick={onGoToMatches}
          className="inline-flex items-center gap-2 h-10 px-6 rounded-xl text-[13px] font-semibold transition active:scale-[0.97]"
          style={{ background: TOKENS.color.primary, color: '#fff' }}
        >
          Browse Matches →
        </button>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnalyticsDashboard({ onGoToMatches }: { onGoToMatches?: () => void } = {}) {
  const [data,    setData]    = useState<AnalyticsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)

  useEffect(() => {
    fetchAnalyticsSummary()
      .then(setData)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Skeleton />

  if (error || !data) {
    return (
      <div className="flex items-center justify-center h-80 text-sm"
        style={{ color: TOKENS.color.danger }}>
        Failed to load analytics. {error}
      </div>
    )
  }

  // Zero-data empty state — guide the user to their first applications
  if (data.total_applications === 0) {
    return <GetStartedOverlay onGoToMatches={onGoToMatches} />
  }

  // maxCount: only non-zero stages drive the scale so zero rails don't count
  const maxCount = Math.max(...data.funnel_stages.map(s => s.count), 1)

  // Skills sorted by count desc so the most-frequent appear first
  const sortedKeywords = [...data.top_keywords].sort((a, b) => b.count - a.count)

  // Companies already sorted by count desc from backend
  const topCompanies  = data.top_companies ?? []
  const maxCompanyCount = Math.max(...topCompanies.map(c => c.count), 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, paddingBottom: 40 }}>

      {/* ── Page header ── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: TOKENS.color.ink, margin: 0 }}>
            Job Search Analytics
          </h1>
          <p style={{ fontSize: 13, color: TOKENS.color.muted, marginTop: 5 }}>
            Your pipeline performance at a glance
          </p>
        </div>

      </div>

      {/* ── KPI cards ── */}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <KpiCard
          label="Total Applications"
          value={data.total_applications}
          sub="Submitted to active pipeline stages"
          accentColor={TOKENS.color.ink}
        />
        <KpiCard
          label="Active Processes"
          value={data.active_processes}
          sub="Processes currently in progress"
          accentColor={TOKENS.color.primary}
        />
        <KpiCard
          label="Interview Rate"
          value={`${data.interview_conversion_rate}%`}
          sub="Applications that reached interview stage"
          accentColor={
            data.interview_conversion_rate >= 20
              ? TOKENS.color.success
              : TOKENS.color.warn
          }
        />
      </div>

      {/* ── Charts row ── */}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'stretch' }}>

        {/* Pipeline funnel — always renders all 6 stages from backend */}
        <Panel title="Current Pipeline Distribution">
          {data.funnel_stages.map((s, i) => (
            <FunnelRow
              key={s.stage}
              stage={s.stage}
              count={s.count}
              maxCount={maxCount}
              isLast={i === data.funnel_stages.length - 1}
            />
          ))}
        </Panel>

        {/* Top companies from CRM data */}
        <Panel title="Top Companies Applied To">
          {topCompanies.length === 0 ? (
            <EmptyHint message="Submit applications and they'll appear here, grouped by company." />
          ) : (
            topCompanies.map((c, i) => (
              <CompanyRow
                key={c.company}
                company={c.company}
                count={c.count}
                maxCount={maxCompanyCount}
                isLast={i === topCompanies.length - 1}
              />
            ))
          )}
        </Panel>

        {/* Top skills cloud */}
        <Panel title="Top Skills in Tailored CVs">
          {sortedKeywords.length === 0 ? (
            <EmptyHint message="Generate tailored CVs and apply to see your most-used skills here." />
          ) : (
            <div className="flex flex-wrap gap-2" style={{ alignContent: 'flex-start' }}>
              {sortedKeywords.map(kw => (
                <KeywordTag key={kw.keyword} keyword={kw.keyword} count={kw.count} />
              ))}
            </div>
          )}
        </Panel>

      </div>
    </div>
  )
}
