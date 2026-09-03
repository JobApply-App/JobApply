'use client'

import { useEffect, useState } from 'react'
import Link        from 'next/link'
import AuthGuard   from '@/components/AuthGuard'
import { useI18n } from '@/contexts/I18nContext'
import { fetchAllJobs } from '@/lib/api'
import type { AllJobItem } from '@/lib/api'

// ── Real jobs, not a mockup ───────────────────────────────────────────────────
//
// This page previously rendered six hardcoded listings at real companies
// (Monday.com, Wix, Fiverr, Lightricks, Gong, Stripe) under a "Trending jobs
// — updated daily based on market demand" heading. Nothing on screen marked
// them as fake, so the first screen after signup advertised openings that did
// not exist at companies that never posted them.
//
// It now reads the same global catalogue the All Jobs tab does. If the
// catalogue is empty the page says so — it must never fall back to invented
// listings, which is the exact failure being corrected here.

// One page of recent jobs to sample from. Larger than the six shown because
// the selection below spreads across seniority and discipline, and a narrow
// sample would collapse to whatever was scraped last — six backend roles at
// one company, which shows range to nobody.
const SAMPLE_SIZE   = 100
const DISPLAY_COUNT = 6

function formatLocation(location: AllJobItem['location']): string | null {
  if (!location) return null
  const parts = [location.city, location.district, location.country]
    .filter((p): p is string => !!p && p.trim() !== '')
  return parts.length ? parts.join(', ') : null
}

/**
 * Pick a varied handful out of the sample.
 *
 * The goal is to show the breadth of what the product covers — a junior role
 * next to a senior one, engineering next to marketing — rather than the six
 * most recently scraped rows, which in practice cluster hard around whichever
 * source ran last.
 *
 * Round-robins across seniority buckets, and within each bucket prefers a
 * discipline not already on screen. One role per company, so a single
 * employer with forty open positions cannot take the whole grid.
 */
function pickVaried(jobs: AllJobItem[], count: number): AllJobItem[] {
  const buckets = new Map<string, AllJobItem[]>()
  for (const job of jobs) {
    if (!job.job_title) continue
    const key = job.seniority_level ?? 'unspecified'
    const bucket = buckets.get(key)
    if (bucket) bucket.push(job)
    else buckets.set(key, [job])
  }

  const picked:       AllJobItem[] = []
  const seenCompany:  Set<string>  = new Set()
  const seenFunction: Set<string>  = new Set()
  const order = Array.from(buckets.keys())

  // Two passes: the first refuses a discipline already shown, the second
  // drops that preference so a small catalogue still fills the grid rather
  // than rendering three cards and a gap.
  for (const requireNewFunction of [true, false]) {
    let progressed = true
    while (picked.length < count && progressed) {
      progressed = false
      for (const key of order) {
        if (picked.length >= count) break
        const bucket = buckets.get(key)
        if (!bucket?.length) continue

        const idx = bucket.findIndex(job => {
          const company = job.company_name?.toLowerCase().trim()
          if (company && seenCompany.has(company)) return false
          if (!requireNewFunction) return true
          const fn = job.job_function?.[0]
          return !fn || !seenFunction.has(fn)
        })
        if (idx === -1) continue

        const [job] = bucket.splice(idx, 1)
        picked.push(job)
        progressed = true
        const company = job.company_name?.toLowerCase().trim()
        if (company) seenCompany.add(company)
        const fn = job.job_function?.[0]
        if (fn) seenFunction.add(fn)
      }
    }
    if (picked.length >= count) break
  }

  return picked
}

// ── Sub-components ────────────────────────────────────────────────────────────

function CompanyAvatar({ name }: { name: string }) {
  const initials = name.split(' ').slice(0, 2).map(w => w[0]).join('')
  const hue = name.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0) % 360
  return (
    <div
      className="w-10 h-10 rounded-xl flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
      style={{ background: `hsl(${hue},55%,45%)` }}
      aria-hidden="true"
    >
      {initials}
    </div>
  )
}

function MatchScoreTeaser() {
  // Inviting placeholder — replaces the old "Match score pending" +
  // "Complete your profile to unlock" pair that read like an error state.
  const D = useI18n().t.discover
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-teal-700 bg-ja-primarySubtle rounded-full px-2.5 py-1">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
      </svg>
      {D.teaser}
    </span>
  )
}

function JobCard({ job }: { job: AllJobItem }) {
  const D = useI18n().t.discover
  const company  = job.company_name?.trim() || D.unknown_company
  const location = formatLocation(job.location)
  // job_function is the discipline (Engineering, Marketing…); seniority sits
  // beside it so the range across the grid is legible at a glance.
  const tags = [job.seniority_level, ...(job.job_function ?? [])]
    .filter((t): t is string => !!t && t.trim() !== '')
    .slice(0, 3)

  return (
    <a
      href={job.job_url}
      target="_blank"
      rel="noopener noreferrer"
      className="bg-white rounded-2xl border border-slate-100 p-5 flex flex-col gap-4 shadow-elevation-1 hover:shadow-elevation-2 transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ja-primary"
    >
      <div className="flex items-start gap-3">
        <CompanyAvatar name={company} />
        <div className="flex-1 min-w-0">
          {/* dir="auto" per field: titles and company names arrive in Hebrew
              or English depending on the source, independent of UI language. */}
          <h2 dir="auto" className="text-[14px] font-semibold text-slate-900 leading-tight truncate text-start">
            {job.job_title}
          </h2>
          <p dir="auto" className="text-[12px] text-slate-500 mt-0.5 truncate text-start">
            {company}{location ? ` · ${location}` : ''}
          </p>
        </div>
        {job.posted_text && (
          <span className="text-[11px] text-slate-400 flex-shrink-0 mt-0.5">{job.posted_text}</span>
        )}
      </div>

      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map(tag => (
            <span
              key={tag}
              className="text-[11px] px-2 py-0.5 rounded-md font-medium bg-ja-primarySubtle text-teal-700"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center pt-1 border-t border-slate-50">
        <MatchScoreTeaser />
      </div>
    </a>
  )
}

function CardSkeleton() {
  return (
    <div className="bg-white rounded-2xl border border-slate-100 p-5 flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-slate-100 animate-pulse flex-shrink-0" />
        <div className="flex-1 space-y-2">
          <div className="h-3.5 w-3/4 rounded bg-slate-100 animate-pulse" />
          <div className="h-3 w-1/2 rounded bg-slate-100 animate-pulse" />
        </div>
      </div>
      <div className="flex gap-1.5">
        <div className="h-4 w-16 rounded bg-slate-100 animate-pulse" />
        <div className="h-4 w-20 rounded bg-slate-100 animate-pulse" />
      </div>
      <div className="h-6 w-40 rounded-full bg-slate-100 animate-pulse" />
    </div>
  )
}

// ── Page content ──────────────────────────────────────────────────────────────

function DiscoverContent() {
  const D = useI18n().t.discover
  const [jobs,   setJobs]   = useState<AllJobItem[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetchAllJobs(1, SAMPLE_SIZE, undefined, 'recent', controller.signal)
      .then(page => setJobs(pickVaried(page.items, DISPLAY_COUNT)))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        // A failure here shows an error state, never invented listings.
        setFailed(true)
        setJobs([])
      })
    return () => controller.abort()
  }, [])

  const loading = jobs === null

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Single primary CTA policy: the "Complete profile" banner below is the
          one and only profile CTA on this page — no duplicate header button. */}
      <header className="bg-white border-b border-slate-100 sticky top-0 z-20">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center">
          <span className="text-base font-extrabold tracking-tight text-slate-900">JobApply</span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10 space-y-8">

        {/* Profile prompt banner */}
        <div
          className="rounded-2xl p-6 flex flex-col sm:flex-row sm:items-center gap-4 border border-white/[0.06]"
          style={{ background: 'linear-gradient(135deg, var(--ja-ink) 0%, var(--ja-ink-deep) 100%)' }}
        >
          <div className="flex-1 space-y-1">
            <p className="text-white font-semibold text-[15px]">{D.banner_title}</p>
            <p className="text-[13px] text-ja-subtle">{D.banner_body}</p>
          </div>
          <Link
            href="/onboarding"
            className="flex-shrink-0 text-sm font-semibold px-5 py-2.5 rounded-xl text-white text-center bg-ja-primary hover:bg-ja-primaryHover transition-colors"
          >
            {D.complete_cta}
          </Link>
        </div>

        {/* Header */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-slate-900">{D.heading}</h1>
            <p className="text-sm text-slate-500 mt-0.5">{D.subheading}</p>
          </div>
          {!loading && jobs.length > 0 && (
            <span className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-ja-primarySubtle text-teal-700 flex-shrink-0">
              {D.roles_count.replace('{n}', String(jobs.length))}
            </span>
          )}
        </div>

        {/* Job grid */}
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: DISPLAY_COUNT }).map((_, i) => <CardSkeleton key={i} />)}
          </div>
        ) : jobs.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {jobs.map(job => <JobCard key={job.id} job={job} />)}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16 gap-2 text-center">
            <p className="text-[14px] font-medium text-slate-600">
              {failed ? D.error_title : D.empty_title}
            </p>
            <p className="text-[13px] text-slate-500 max-w-sm">
              {failed ? D.error_body : D.empty_body}
            </p>
          </div>
        )}

      </main>
    </div>
  )
}

// ── Page (guarded) ────────────────────────────────────────────────────────────

export default function DiscoverPage() {
  return (
    <AuthGuard>
      <DiscoverContent />
    </AuthGuard>
  )
}
