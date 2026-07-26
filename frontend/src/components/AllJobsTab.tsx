'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAllJobs } from '@/hooks/useAllJobs'
import type { AllJobItem } from '@/lib/api'
import { TOKENS } from '@/lib/tokens'

// ── URL <-> pagination state ──────────────────────────────────────────────────

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const
const DEFAULT_PAGE_SIZE = 25

function parsePage(raw: string | null): number {
  const n = raw ? parseInt(raw, 10) : 1
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1
}

function parsePageSize(raw: string | null): number {
  const n = raw ? parseInt(raw, 10) : DEFAULT_PAGE_SIZE
  return (PAGE_SIZE_OPTIONS as readonly number[]).includes(n) ? n : DEFAULT_PAGE_SIZE
}

// ── Source badge ──────────────────────────────────────────────────────────────
// all_jobs is cross-provider (see backend/models/all_jobs.py) — it has no
// LinkedIn-specific `linkedin_status`, just a plain `source` string.

const SOURCE_COLORS: Record<string, string> = {
  linkedin: 'bg-sky-100 text-sky-700',
}

function SourceBadge({ source }: { source: string }) {
  const cls = SOURCE_COLORS[source.toLowerCase()] ?? 'bg-slate-200 text-slate-600'
  return (
    <span className={`text-[10.5px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap ${cls}`}>
      {source.charAt(0).toUpperCase() + source.slice(1).toLowerCase()}
    </span>
  )
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function dash(value: string | null | undefined): string {
  return value && value.trim() ? value : '—'
}

function formatLocation(location: AllJobItem['location']): string {
  if (!location) return '—'
  const parts = [location.city, location.district, location.country]
    .filter((p): p is string => !!p && p.trim() !== '')
  return parts.length ? parts.join(', ') : '—'
}

// ── Company logo with fallback ────────────────────────────────────────────────

function CompanyLogo({ url, company }: { url: string | null; company: string | null }) {
  const [failed, setFailed] = useState(false)
  const label = (company ?? '?').charAt(0).toUpperCase()
  if (!url || failed) {
    return (
      <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center text-[11px] font-semibold text-slate-400 shrink-0">
        {label}
      </div>
    )
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={`${company ?? 'Company'} logo`}
      className="w-8 h-8 rounded-lg object-contain bg-white border border-slate-100 shrink-0"
      onError={() => setFailed(true)}
    />
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

function JobRow({ job }: { job: AllJobItem }) {
  return (
    <div className="flex items-start gap-3 bg-white rounded-2xl border border-slate-100 px-4 py-3 hover:border-slate-200 hover:shadow-sm transition-all duration-150">
      <CompanyLogo url={job.company_logo_url} company={job.company_name} />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <a
            href={job.job_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[13px] font-semibold text-slate-900 hover:text-teal-700 hover:underline truncate"
          >
            {dash(job.job_title)}
          </a>
          <SourceBadge source={job.source} />
        </div>
        <p className="text-[12px] text-slate-500 truncate mt-0.5">
          {dash(job.company_name)} · {formatLocation(job.location)}
        </p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-[11px] text-slate-400">
          <span>{dash(job.employment_type)}</span>
          <span>{dash(job.seniority_level)}</span>
          <span>Posted {dash(job.posted_text)}</span>
        </div>
      </div>

      <div className="text-right shrink-0 hidden sm:block">
        <p className="text-[11px] text-slate-400">First seen {formatDateTime(job.first_seen_at)}</p>
        <p className="text-[11px] text-slate-400 mt-0.5">Last seen {formatDateTime(job.last_seen_at)}</p>
      </div>
    </div>
  )
}

// ── List states (loading / error / empty) ────────────────────────────────────

function JobListSkeleton() {
  return (
    <div className="space-y-2 mt-4">
      {[...Array(6)].map((_, i) => (
        <div key={i} className="h-16 rounded-2xl bg-slate-100 animate-pulse" />
      ))}
    </div>
  )
}

function JobListError({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-40 gap-3 text-sm" style={{ color: TOKENS.color.danger }}>
      <p>Failed to load jobs. {error}</p>
      <button
        onClick={onRetry}
        className="h-8 px-4 rounded-lg text-[12px] font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 transition"
      >
        Retry
      </button>
    </div>
  )
}

function JobListEmpty() {
  return (
    <div className="flex flex-col items-center justify-center h-48 text-slate-400">
      <svg width={36} height={36} viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
        className="mb-3 opacity-40">
        <rect x="3" y="7" width="18" height="13" rx="2" />
        <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      </svg>
      <p className="text-[13px] font-medium text-slate-500">No jobs were found.</p>
    </div>
  )
}

// ── Pagination controls ───────────────────────────────────────────────────────

function PaginationControls({
  page, totalPages, totalItems, pageSize, hasNext, hasPrevious, onPageChange, onPageSizeChange,
}: {
  page: number
  totalPages: number
  totalItems: number
  pageSize: number
  hasNext: boolean
  hasPrevious: boolean
  onPageChange: (p: number) => void
  onPageSizeChange: (s: number) => void
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
      <p className="text-[12px] text-slate-500">
        {totalItems} total result{totalItems === 1 ? '' : 's'}
      </p>

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1.5 text-[12px] text-slate-500">
          Per page
          <select
            value={pageSize}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            className="h-7 rounded-lg border border-slate-200 bg-white text-[12px] text-slate-700 px-1.5"
          >
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
        </label>

        <span className="text-[12px] text-slate-500 whitespace-nowrap">
          Page {totalPages === 0 ? 0 : page} of {totalPages}
        </span>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={!hasPrevious}
            className="h-7 px-3 rounded-lg text-[12px] font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 transition disabled:opacity-40 disabled:hover:bg-white disabled:hover:border-slate-200"
          >
            Previous
          </button>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={!hasNext}
            className="h-7 px-3 rounded-lg text-[12px] font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 transition disabled:opacity-40 disabled:hover:bg-white disabled:hover:border-slate-200"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function AllJobsTab() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const [page, setPage] = useState(() => parsePage(searchParams.get('page')))
  const [pageSize, setPageSize] = useState(() => parsePageSize(searchParams.get('pageSize')))

  // Resync from the URL on browser back/forward (and on the tab-switch push
  // Header.tsx does when the "All Jobs" tab is first clicked — that push
  // carries only ?tab=all-jobs, no page/pageSize, which must reset local
  // state back to page 1 / default page size rather than leaving whatever
  // page the user was on before navigating away). The `useState(() => ...)`
  // initializers above only run once on mount — App Router doesn't remount
  // this component for a same-route history navigation, so without this
  // effect the local state silently drifts out of sync with the URL.
  useEffect(() => {
    setPage(parsePage(searchParams.get('page')))
    setPageSize(parsePageSize(searchParams.get('pageSize')))
  }, [searchParams])

  const { jobs, pagination, loading, error, refetch } = useAllJobs(page, pageSize)

  // Keeps every other existing query param (notably ?tab=all-jobs) intact —
  // only page/pageSize are added/overwritten.
  const syncUrl = useCallback((nextPage: number, nextPageSize: number) => {
    const params = new URLSearchParams(searchParams.toString())
    params.set('tab', 'all-jobs')
    params.set('page', String(nextPage))
    params.set('pageSize', String(nextPageSize))
    router.push(`/?${params.toString()}`, { scroll: false })
  }, [router, searchParams])

  const goToPage = (p: number) => {
    const clamped = Math.max(1, p)
    setPage(clamped)
    syncUrl(clamped, pageSize)
  }

  const changePageSize = (size: number) => {
    setPageSize(size)
    setPage(1)   // reset to page 1 whenever page size changes
    syncUrl(1, size)
  }

  const totalPages = pagination?.total_pages ?? 0
  const totalItems = pagination?.total_items ?? 0
  const hasNext = pagination?.has_next ?? false
  const hasPrevious = pagination?.has_previous ?? false

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold text-slate-900">All Jobs</h2>
        <p className="text-[12px] text-slate-500 mt-0.5">
          {loading && jobs.length === 0 ? '—' : `${totalItems} job${totalItems === 1 ? '' : 's'} across all sources`}
        </p>
      </div>

      {/* First-load skeleton only — a page/pageSize change keeps the
          previous page's rows visible (see useAllJobs's docstring) instead
          of blanking the table, so no skeleton flash on Next/Previous. */}
      {loading && jobs.length === 0 && <JobListSkeleton />}

      {!loading && error && jobs.length === 0 && <JobListError error={error} onRetry={refetch} />}

      {!error && !loading && jobs.length === 0 && <JobListEmpty />}

      {jobs.length > 0 && (
        <div className="space-y-2 mt-4">
          {jobs.map((job) => <JobRow key={job.id} job={job} />)}
        </div>
      )}

      {totalItems > 0 && (
        <PaginationControls
          page={page}
          totalPages={totalPages}
          totalItems={totalItems}
          pageSize={pageSize}
          hasNext={hasNext}
          hasPrevious={hasPrevious}
          onPageChange={goToPage}
          onPageSizeChange={changePageSize}
        />
      )}
    </section>
  )
}
