'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAllJobs } from '@/hooks/useAllJobs'
import { useAllJobsFilterOptions } from '@/hooks/useAllJobsFilterOptions'
import type { AllJobItem, AllJobsFilters, AllJobsSortBy } from '@/lib/api'
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

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"
      className={`transition-transform duration-150 ${expanded ? 'rotate-180' : ''}`}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  )
}

// applicants/industries/description live behind the expand toggle rather
// than always-on — the goal per the design brief was "more info, but not
// cluttered across every job row." All three already ride in the same
// list-query payload (see backend/repositories/all_jobs_repository.py's
// _LIST_VIEW_COLUMNS), so expanding is instant, no extra network call.
function JobRowDetails({ job }: { job: AllJobItem }) {
  const applicantsText = job.applicants?.value != null
    ? `${job.applicants.exact ? '' : 'Fewer than '}${job.applicants.value} applicant${job.applicants.value === 1 ? '' : 's'}`
    : null

  return (
    <div className="mt-2 pt-2 border-t border-slate-100 space-y-2">
      {(applicantsText || (job.industries && job.industries.length > 0)) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
          {applicantsText && <span>{applicantsText}</span>}
          {job.industries?.map((ind) => (
            <span key={ind} dir="auto" className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10.5px] [unicode-bidi:plaintext]">
              {ind}
            </span>
          ))}
        </div>
      )}
      {job.description && (
        <p dir="auto" className="text-[12px] text-slate-600 leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto [unicode-bidi:plaintext] text-start">
          {job.description}
        </p>
      )}
    </div>
  )
}

// Resting/hover/expanded shadows per DESIGN_SYSTEM.md §3 ("multi-layered
// micro-shadows, never flat shadow-sm/md/lg") — same pair used for the
// primary JobCard. Plain Tailwind classes (not JS hover state) so a page of
// 100 rows doesn't re-render on every mouse move.
const SHADOW_REST = 'shadow-[0_1px_3px_rgba(15,23,42,0.04)]'
const SHADOW_HOVER = 'hover:shadow-[0_4px_16px_rgba(15,23,42,0.08),0_1px_3px_rgba(15,23,42,0.05)]'
const SHADOW_EXPANDED = 'shadow-[0_4px_16px_rgba(15,23,42,0.08),0_1px_3px_rgba(15,23,42,0.05)]'

function JobRow({ job }: { job: AllJobItem }) {
  const [expanded, setExpanded] = useState(false)
  const hasDetails = !!job.description || !!job.applicants?.value || (job.industries?.length ?? 0) > 0

  return (
    <div
      className={`bg-white rounded-2xl border px-4 py-3.5 transition-all duration-150 ${SHADOW_REST} ${
        expanded ? `border-slate-200 ${SHADOW_EXPANDED}` : `border-slate-100 hover:border-slate-200 ${SHADOW_HOVER}`
      }`}
    >
      <div className="flex items-start gap-3">
        <CompanyLogo url={job.company_logo_url} company={job.company_name} />

        <div className="flex-1 min-w-0" dir="auto" style={{ textAlign: 'start', unicodeBidi: 'plaintext' }}>
          <div className="flex items-center gap-2 flex-wrap">
            <a
              href={job.job_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[13.5px] font-semibold text-slate-900 hover:text-teal-700 hover:underline truncate"
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

        <div className="flex items-start gap-2 shrink-0">
          <div className="text-right hidden sm:block">
            <p className="text-[11px] text-slate-400">First seen {formatDateTime(job.first_seen_at)}</p>
            <p className="text-[11px] text-slate-400 mt-0.5">Last seen {formatDateTime(job.last_seen_at)}</p>
          </div>
          {hasDetails && (
            <button
              onClick={() => setExpanded((e) => !e)}
              aria-label={expanded ? 'Hide details' : 'Show details'}
              className="h-6 w-6 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition"
            >
              <ChevronIcon expanded={expanded} />
            </button>
          )}
        </div>
      </div>

      {expanded && hasDetails && <JobRowDetails job={job} />}
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

// ── Filter bar ────────────────────────────────────────────────────────────────
// Raw input state — kept separate from the AllJobsFilters actually sent to
// the API so number fields can hold an in-progress/invalid string while
// typing without crashing the fetch, and so multi-select fields can hold
// an in-progress selection distinct from the debounced/committed one.

interface FilterInputs {
  seniority_level:     string[]
  employment_type:     string[]
  job_function:        string[]
  industry:            string[]
  company:             string
  title:               string
  min_applicants:      string
  max_applicants:      string
  posted_within_hours: string
}

const EMPTY_FILTER_INPUTS: FilterInputs = {
  seniority_level: [], employment_type: [], job_function: [], industry: [],
  company: '', title: '', min_applicants: '', max_applicants: '', posted_within_hours: '',
}

const POSTED_WITHIN_OPTIONS = [
  { label: 'Any time', value: '' },
  { label: 'Last 24 hours', value: '24' },
  { label: 'Last 3 days', value: '72' },
  { label: 'Last 7 days', value: '168' },
  { label: 'Last 30 days', value: '720' },
]

const SORT_OPTIONS: { label: string; value: AllJobsSortBy }[] = [
  { label: 'Recently scraped', value: 'recent' },
  { label: 'Newest posted', value: 'posted' },
  { label: 'Most applicants', value: 'applicants_desc' },
  { label: 'Fewest applicants', value: 'applicants_asc' },
  { label: 'Company (A-Z)', value: 'company' },
]

function selectClass(hasValue: boolean): string {
  const base = 'h-8 rounded-lg border bg-white text-[12px] px-2 max-w-[160px] truncate'
  return hasValue
    ? `${base} border-teal-300 text-teal-800`
    : `${base} border-slate-200 text-slate-600`
}

// ── Multi-select dropdown ────────────────────────────────────────────────────
// Plain HTML <select multiple> requires ctrl/cmd-click to select more than
// one option — not discoverable — so this is a small custom checkbox-list
// popover instead. Closes on outside click; no external dependency.

function useClickOutside(ref: React.RefObject<HTMLElement>, onOutside: () => void) {
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [ref, onOutside])
}

function MultiSelectDropdown({
  label, options, selected, onChange,
}: {
  label: string
  options: string[]
  selected: string[]
  onChange: (next: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useClickOutside(ref, () => setOpen(false))

  const toggleValue = (v: string) => {
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v])
  }

  const buttonLabel = selected.length === 0 ? label
    : selected.length === 1 ? selected[0]
    : `${label} (${selected.length})`

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={selectClass(selected.length > 0)}
      >
        {buttonLabel}
      </button>
      {open && (
        <div className="absolute z-10 mt-1 max-h-56 w-80 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg py-1">
          {options.length === 0 && (
            <p className="px-3 py-1.5 text-[12px] text-slate-400">No options</p>
          )}
          {options.map((opt) => (
            <label key={opt} className="flex items-start gap-2 px-3 py-1.5 text-[12px] text-slate-700 hover:bg-slate-50 cursor-pointer">
              <input
                type="checkbox"
                checked={selected.includes(opt)}
                onChange={() => toggleValue(opt)}
                className="accent-teal-600 mt-0.5 shrink-0"
              />
              {/* No truncation here — some real industry names (e.g.
                  "Technology, Information and Internet") contain their own
                  internal comma and read as a fragment if cut off with
                  "...", which looks like a splitting bug but isn't one. */}
              <span className="leading-snug">{opt}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

function FilterBar({
  inputs, onChange, onMultiChange, onClear, hasActiveFilters, options, sortBy, onSortChange,
}: {
  inputs: FilterInputs
  onChange: (field: 'company' | 'title' | 'min_applicants' | 'max_applicants' | 'posted_within_hours', value: string) => void
  onMultiChange: (field: 'seniority_level' | 'employment_type' | 'job_function' | 'industry', value: string[]) => void
  onClear: () => void
  hasActiveFilters: boolean
  options: {
    seniority_levels: string[]
    employment_types: string[]
    job_functions:    string[]
    industries:       string[]
  } | null
  sortBy: AllJobsSortBy
  onSortChange: (value: AllJobsSortBy) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 pb-1">
      <input
        type="text"
        value={inputs.company}
        onChange={(e) => onChange('company', e.target.value)}
        placeholder="Company"
        className="h-8 w-32 rounded-lg border border-slate-200 bg-white text-[12px] px-2.5 placeholder:text-slate-400"
      />
      <input
        type="text"
        value={inputs.title}
        onChange={(e) => onChange('title', e.target.value)}
        placeholder="Job title"
        className="h-8 w-36 rounded-lg border border-slate-200 bg-white text-[12px] px-2.5 placeholder:text-slate-400"
      />

      <MultiSelectDropdown
        label="Seniority"
        options={options?.seniority_levels ?? []}
        selected={inputs.seniority_level}
        onChange={(v) => onMultiChange('seniority_level', v)}
      />
      <MultiSelectDropdown
        label="Employment type"
        options={options?.employment_types ?? []}
        selected={inputs.employment_type}
        onChange={(v) => onMultiChange('employment_type', v)}
      />
      <MultiSelectDropdown
        label="Function"
        options={options?.job_functions ?? []}
        selected={inputs.job_function}
        onChange={(v) => onMultiChange('job_function', v)}
      />
      <MultiSelectDropdown
        label="Industry"
        options={options?.industries ?? []}
        selected={inputs.industry}
        onChange={(v) => onMultiChange('industry', v)}
      />

      <select
        value={inputs.posted_within_hours}
        onChange={(e) => onChange('posted_within_hours', e.target.value)}
        className={selectClass(!!inputs.posted_within_hours)}
      >
        {POSTED_WITHIN_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>

      <div className="flex items-center gap-1">
        <input
          type="number"
          min={0}
          value={inputs.min_applicants}
          onChange={(e) => onChange('min_applicants', e.target.value)}
          placeholder="Min applicants"
          className="h-8 w-[92px] rounded-lg border border-slate-200 bg-white text-[12px] px-2 placeholder:text-slate-400"
        />
        <span className="text-[11px] text-slate-400">–</span>
        <input
          type="number"
          min={0}
          value={inputs.max_applicants}
          onChange={(e) => onChange('max_applicants', e.target.value)}
          placeholder="Max"
          className="h-8 w-16 rounded-lg border border-slate-200 bg-white text-[12px] px-2 placeholder:text-slate-400"
        />
      </div>

      <label className="flex items-center gap-1.5 text-[12px] text-slate-500 ml-auto">
        Sort
        <select
          value={sortBy}
          onChange={(e) => onSortChange(e.target.value as AllJobsSortBy)}
          className="h-8 rounded-lg border border-slate-200 bg-white text-[12px] text-slate-700 px-2"
        >
          {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </label>

      {hasActiveFilters && (
        <button
          onClick={onClear}
          className="h-8 px-3 rounded-lg text-[12px] font-medium text-slate-500 hover:text-slate-700 hover:bg-slate-50 transition"
        >
          Clear filters
        </button>
      )}
    </div>
  )
}

// ── Active filter chips ──────────────────────────────────────────────────────
// Surfaces exactly what's currently filtered as removable pills — with 9
// independent filter fields, the filter bar alone doesn't show *what* is
// applied once a dropdown closes, only that something is (via its teal
// border). One glance here + a click to drop a single field beats re-opening
// each control to check its state.

const MULTI_FILTER_LABELS: Record<'seniority_level' | 'employment_type' | 'job_function' | 'industry', string> = {
  seniority_level: 'Seniority',
  employment_type: 'Employment type',
  job_function:    'Function',
  industry:        'Industry',
}

function ActiveFilterChips({
  inputs, onChange, onMultiChange,
}: {
  inputs: FilterInputs
  onChange: (field: 'company' | 'title' | 'min_applicants' | 'max_applicants' | 'posted_within_hours', value: string) => void
  onMultiChange: (field: 'seniority_level' | 'employment_type' | 'job_function' | 'industry', value: string[]) => void
}) {
  const chips: { key: string; label: string; onRemove: () => void }[] = []

  if (inputs.company) chips.push({ key: 'company', label: `Company: ${inputs.company}`, onRemove: () => onChange('company', '') })
  if (inputs.title) chips.push({ key: 'title', label: `Title: ${inputs.title}`, onRemove: () => onChange('title', '') })

  ;(['seniority_level', 'employment_type', 'job_function', 'industry'] as const).forEach((field) => {
    const values = inputs[field]
    if (values.length > 0) {
      chips.push({
        key: field,
        label: `${MULTI_FILTER_LABELS[field]}: ${values.join(', ')}`,
        onRemove: () => onMultiChange(field, []),
      })
    }
  })

  if (inputs.posted_within_hours) {
    const opt = POSTED_WITHIN_OPTIONS.find((o) => o.value === inputs.posted_within_hours)
    chips.push({ key: 'posted', label: opt?.label ?? 'Posted within', onRemove: () => onChange('posted_within_hours', '') })
  }

  if (inputs.min_applicants || inputs.max_applicants) {
    const label = inputs.min_applicants && inputs.max_applicants
      ? `Applicants: ${inputs.min_applicants}–${inputs.max_applicants}`
      : inputs.min_applicants
      ? `Applicants: ≥ ${inputs.min_applicants}`
      : `Applicants: ≤ ${inputs.max_applicants}`
    chips.push({
      key: 'applicants',
      label,
      onRemove: () => { onChange('min_applicants', ''); onChange('max_applicants', '') },
    })
  }

  if (chips.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-1.5 -mt-1">
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex items-center gap-1 h-6 pl-2.5 pr-1.5 rounded-full bg-teal-50 text-teal-800 text-[11px] font-medium max-w-[280px]"
        >
          <span className="truncate">{chip.label}</span>
          <button
            onClick={chip.onRemove}
            aria-label={`Remove filter: ${chip.label}`}
            className="shrink-0 h-4 w-4 flex items-center justify-center rounded-full text-teal-600 hover:bg-teal-100 hover:text-teal-900 transition"
          >
            ×
          </button>
        </span>
      ))}
    </div>
  )
}

// ── Pagination controls ───────────────────────────────────────────────────────
// Numbered page buttons (with an ellipsis for large page counts) instead of a
// bare Previous/Next pair — lets a user jump straight to page 5 of 7 instead
// of clicking Next four times, same convention as most job-board paginators.

function buildPageList(current: number, total: number): (number | 'ellipsis')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages = new Set<number>([1, total, current, current - 1, current + 1])
  const sorted = Array.from(pages).filter((p) => p >= 1 && p <= total).sort((a, b) => a - b)
  const withEllipsis: (number | 'ellipsis')[] = []
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) withEllipsis.push('ellipsis')
    withEllipsis.push(p)
  })
  return withEllipsis
}

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
  const rangeStart = totalItems === 0 ? 0 : (page - 1) * pageSize + 1
  const rangeEnd = Math.min(page * pageSize, totalItems)
  const pageList = buildPageList(page, totalPages)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
      <p className="text-[12px] text-slate-500">
        Showing <span className="font-medium text-slate-700">{rangeStart}–{rangeEnd}</span> of{' '}
        <span className="font-medium text-slate-700">{totalItems}</span> result{totalItems === 1 ? '' : 's'}
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

        <div className="flex items-center gap-1">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={!hasPrevious}
            aria-label="Previous page"
            className="h-7 w-7 flex items-center justify-center rounded-lg text-[12px] font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 transition disabled:opacity-40 disabled:hover:bg-white disabled:hover:border-slate-200"
          >
            ‹
          </button>

          {pageList.map((p, i) =>
            p === 'ellipsis' ? (
              <span key={`e${i}`} className="w-6 text-center text-[12px] text-slate-400 select-none">…</span>
            ) : (
              <button
                key={p}
                onClick={() => onPageChange(p)}
                aria-current={p === page ? 'page' : undefined}
                className={`h-7 min-w-7 px-2 rounded-lg text-[12px] font-medium transition tabular-nums ${
                  p === page
                    ? 'bg-teal-600 text-white'
                    : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300'
                }`}
              >
                {p}
              </button>
            )
          )}

          <button
            onClick={() => onPageChange(page + 1)}
            disabled={!hasNext}
            aria-label="Next page"
            className="h-7 w-7 flex items-center justify-center rounded-lg text-[12px] font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 transition disabled:opacity-40 disabled:hover:bg-white disabled:hover:border-slate-200"
          >
            ›
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

  // ── Filters ──────────────────────────────────────────────────────────────
  // Not URL-synced (unlike page/pageSize) — kept as local component state
  // to avoid combinatorial URL-parsing edge cases across 9 optional fields;
  // filters simply reset on a fresh tab visit, same as most job boards.
  const [filterInputs, setFilterInputs] = useState<FilterInputs>(EMPTY_FILTER_INPUTS)
  const [committedFilters, setCommittedFilters] = useState<FilterInputs>(EMPTY_FILTER_INPUTS)
  const filterOptions = useAllJobsFilterOptions()

  // Debounce text/number inputs so every keystroke doesn't fire a request —
  // selects also ride this same debounce (350ms is imperceptible for a
  // discrete choice) rather than maintaining two separate code paths.
  useEffect(() => {
    const t = setTimeout(() => setCommittedFilters(filterInputs), 350)
    return () => clearTimeout(t)
  }, [filterInputs])

  const [sortBy, setSortBy] = useState<AllJobsSortBy>('recent')

  const filters: AllJobsFilters = useMemo(() => ({
    seniority_level:     committedFilters.seniority_level.length ? committedFilters.seniority_level : undefined,
    employment_type:     committedFilters.employment_type.length ? committedFilters.employment_type : undefined,
    job_function:        committedFilters.job_function.length ? committedFilters.job_function : undefined,
    industry:            committedFilters.industry.length ? committedFilters.industry : undefined,
    company:             committedFilters.company || undefined,
    title:               committedFilters.title || undefined,
    min_applicants:      committedFilters.min_applicants !== '' ? Number(committedFilters.min_applicants) : undefined,
    max_applicants:      committedFilters.max_applicants !== '' ? Number(committedFilters.max_applicants) : undefined,
    posted_within_hours: committedFilters.posted_within_hours !== '' ? Number(committedFilters.posted_within_hours) : undefined,
  }), [committedFilters])

  const { jobs, pagination, loading, error, refetch } = useAllJobs(page, pageSize, filters, sortBy)

  // Keeps every other existing query param (notably ?tab=all-jobs) intact —
  // only page/pageSize are added/overwritten.
  const syncUrl = useCallback((nextPage: number, nextPageSize: number) => {
    const params = new URLSearchParams(searchParams.toString())
    params.set('tab', 'all-jobs')
    params.set('page', String(nextPage))
    params.set('pageSize', String(nextPageSize))
    router.push(`/?${params.toString()}`, { scroll: false })
  }, [router, searchParams])

  // Anchors the top of the job list — `router.push(..., { scroll: false })`
  // above deliberately suppresses Next.js's own scroll-to-top (it would jump
  // the whole page, including the header, on every same-route URL sync), but
  // that means changing pages left the viewport wherever the user scrolled
  // to on the *previous* page's rows, looking at content that no longer
  // matches. Scroll to this anchor by hand instead, on page/page-size change.
  const jobsListTopRef = useRef<HTMLDivElement>(null)
  const scrollToListTop = () => {
    jobsListTopRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const goToPage = (p: number) => {
    const clamped = Math.max(1, p)
    setPage(clamped)
    syncUrl(clamped, pageSize)
    scrollToListTop()
  }

  const changePageSize = (size: number) => {
    setPageSize(size)
    setPage(1)   // reset to page 1 whenever page size changes
    syncUrl(1, size)
    scrollToListTop()
  }

  // Reset to page 1 whenever the *committed* (debounced) filters or the
  // sort order change — skips the initial mount so loading the tab fresh
  // doesn't rewrite the URL's page param right away.
  const skipFirstFilterReset = useRef(true)
  useEffect(() => {
    if (skipFirstFilterReset.current) {
      skipFirstFilterReset.current = false
      return
    }
    setPage(1)
    syncUrl(1, pageSize)
  }, [committedFilters, sortBy])  // eslint-disable-line react-hooks/exhaustive-deps

  const updateFilter = (
    field: 'company' | 'title' | 'min_applicants' | 'max_applicants' | 'posted_within_hours', value: string,
  ) => {
    setFilterInputs((prev) => ({ ...prev, [field]: value }))
  }

  const updateMultiFilter = (
    field: 'seniority_level' | 'employment_type' | 'job_function' | 'industry', value: string[],
  ) => {
    setFilterInputs((prev) => ({ ...prev, [field]: value }))
  }

  const clearFilters = () => setFilterInputs(EMPTY_FILTER_INPUTS)

  const hasActiveFilters = Object.values(filterInputs).some((v) => Array.isArray(v) ? v.length > 0 : v !== '')

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

      <FilterBar
        inputs={filterInputs}
        onChange={updateFilter}
        onMultiChange={updateMultiFilter}
        onClear={clearFilters}
        hasActiveFilters={hasActiveFilters}
        options={filterOptions}
        sortBy={sortBy}
        onSortChange={setSortBy}
      />

      <ActiveFilterChips inputs={filterInputs} onChange={updateFilter} onMultiChange={updateMultiFilter} />

      {/* Scroll target for page/page-size changes — sits right above the
          list so "back to top" lands on the first job row, not the header.
          scroll-mt-20 (80px) reserves room for Header.tsx's sticky bar
          (h-14/60px) — without it, scrollIntoView's block:'start' scrolls
          this anchor flush to the viewport top, where the sticky header
          then covers it, so the scroll visually looks like it fell short. */}
      <div ref={jobsListTopRef} className="scroll-mt-20" />

      {/* First-load skeleton only — a page/pageSize/filter change keeps the
          previous page's rows visible (see useAllJobs's docstring) instead
          of blanking the table, so no skeleton flash on Next/Previous. A
          subtle opacity dim on the (still-interactive) old rows is enough
          feedback that a new page is loading without hiding content. */}
      {loading && jobs.length === 0 && <JobListSkeleton />}

      {!loading && error && jobs.length === 0 && <JobListError error={error} onRetry={refetch} />}

      {!error && !loading && jobs.length === 0 && <JobListEmpty />}

      {jobs.length > 0 && (
        <div className={`space-y-2 mt-4 transition-opacity duration-150 ${loading ? 'opacity-50' : 'opacity-100'}`}>
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
