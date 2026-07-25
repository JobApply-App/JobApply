'use client'
import { useState, useEffect, useCallback, useMemo } from 'react'
import { TOKENS } from '@/lib/tokens'
import type { ApiFeedJob, JobSourceType, JobStatus } from '@/lib/apiTypes'
import type { Job, ReasonKind, AutomationSettings, WorkMode, Region, CompanyStage } from '@/lib/data'
import { fetchFeedJobs, forceRefreshAllScores, updateJobStatus, backfillJdText, startAnalysis, setAuthToken } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import { JobCard } from './JobCard'
import { ApplierPreview } from './ApplierPreview'

// ── Preference filter helpers (client-side, Matches page only) ─────────────────

/**
 * Keyword sets for work-mode detection on free-form location / title strings.
 * These are applied client-side because backend location strings are unstructured.
 */
const WORK_MODE_KEYWORDS: Record<WorkMode, string[]> = {
  remote: ['remote', 'wfh', 'work from home', 'fully remote', 'full remote'],
  hybrid: ['hybrid'],
  onsite: [],  // "onsite" = not remote AND not hybrid
}

const REGION_KEYWORDS: Record<Region, string[]> = {
  'tel-aviv':  ['tel aviv', 'tlv', 'tel-aviv', 'jaffa', 'yafo'],
  central:     ['rishon', 'lod', 'ramla', 'rehovot', 'petah tikva', 'petach tikva',
                'holon', 'bat yam', 'ramat gan', 'givatayim', 'bnei brak', 'central'],
  sharon:      ['herzliya', "ra'anana", 'raanana', 'netanya', 'kfar saba', 'hod hasharon',
                'even yehuda', 'sharon'],
  haifa:       ['haifa', 'hadera', 'tirat carmel', 'krayot'],
  jerusalem:   ['jerusalem', 'yerushalayim', 'modiin', 'mevasseret'],
  south:       ['beer sheva', "be'er sheva", 'beersheba', 'eilat', 'ashdod',
                'ashkelon', 'kiryat gat'],
}

/** Company-stage heuristics on job title / company name strings. */
const STAGE_KEYWORDS: Record<CompanyStage, string[]> = {
  startup:    ['startup', 'start-up', 'seed', 'pre-seed', 'series a', 'stealth'],
  growth:     ['series b', 'series c', 'series d', 'scale', 'scaleup', 'growth stage'],
  enterprise: ['enterprise', 'corp', 'global', 'fortune', 'public company', 'listed'],
}

function locLower(job: ApiFeedJob): string {
  return (job.location ?? '').toLowerCase()
}
function titleLower(job: ApiFeedJob): string {
  return (job.title ?? '').toLowerCase() + ' ' + (job.company ?? '').toLowerCase()
}

function jobMatchesWorkMode(job: ApiFeedJob, modes: WorkMode[]): boolean {
  if (modes.length === 0) return true
  const loc   = locLower(job)
  const isRemote = WORK_MODE_KEYWORDS.remote.some(k => loc.includes(k))
  const isHybrid = WORK_MODE_KEYWORDS.hybrid.some(k => loc.includes(k))
  const isOnsite = !isRemote && !isHybrid

  return modes.some(m => {
    if (m === 'remote') return isRemote
    if (m === 'hybrid') return isHybrid
    if (m === 'onsite') return isOnsite
    return false
  })
}

function jobMatchesRegion(job: ApiFeedJob, regions: Region[]): boolean {
  if (regions.length === 0) return true
  const loc = locLower(job)
  return regions.some(r => REGION_KEYWORDS[r].some(k => loc.includes(k)))
}

function jobMatchesStage(job: ApiFeedJob, stages: CompanyStage[]): boolean {
  if (stages.length === 0) return true
  const text = titleLower(job)
  return stages.some(s => STAGE_KEYWORDS[s].some(k => text.includes(k)))
}

/** Returns true if the job should be shown given the current preferences. */
function passesPreferences(job: ApiFeedJob, prefs: AutomationSettings): boolean {
  // min_score is enforced server-side; repeat client-side as safety net
  if (prefs.minScore > 0 && job.match_score < prefs.minScore) return false
  if (!jobMatchesWorkMode(job, prefs.workModes))     return false
  if (!jobMatchesRegion(job,   prefs.regions))       return false
  if (!jobMatchesStage(job,    prefs.companyStages)) return false
  return true
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function toJob(f: ApiFeedJob, rank: number): Job {
  return {
    id:         f.job_id,
    title:      f.title,
    company:    f.company,
    location:   f.location,
    postedAt:   f.posted_at,
    postedRank: rank,
    // Always use match_score (the LLM-enriched composite) — never f.score,
    // which is the stale s1 local proxy value stored in the `score` DB column
    // and is never updated by the two-phase scoring pipeline.
    score:      f.match_score,
    isNew:      f.is_new,
    reasons:    f.reasons.map(r => ({ kind: r.kind as ReasonKind, label: r.label })),
    whyRon:     f.why_ron,
  }
}

const PAGE_SIZE = 50

// ── Spinner ───────────────────────────────────────────────────────────────────

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'spin 0.8s linear infinite' }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.25" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ message, tone = 'success' }: { message: string; tone?: 'success' | 'error' }) {
  return (
    <div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl shadow-floating text-[13px] font-medium text-white"
      style={{ background: tone === 'success' ? TOKENS.color.success : TOKENS.color.danger }}
    >
      {message}
    </div>
  )
}

// ── Search bar ────────────────────────────────────────────────────────────────

function SearchBar({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative">
      <svg
        className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
        width={14} height={14} viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <input
        type="text"
        placeholder="Search by title or company…"
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full h-9 pl-8 pr-8 rounded-lg border border-slate-200 bg-white text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-400 transition"
      />
      {value && (
        <button
          onClick={() => onChange('')}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
          aria-label="Clear search"
        >
          <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.5" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  )
}

// ── Source filter chips ───────────────────────────────────────────────────────

type SourceFilter = 'all' | JobSourceType

const SOURCE_CHIP_OPTIONS: { id: SourceFilter; label: string }[] = [
  { id: 'all',          label: 'All Sources'    },
  { id: 'company_site', label: '🏢 Company Sites' },
  { id: 'linkedin',     label: '💼 LinkedIn'      },
  { id: 'other',        label: 'Other'            },
]

function SourceChips({
  active,
  setActive,
}: {
  active:    SourceFilter
  setActive: (s: SourceFilter) => void
}) {
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {SOURCE_CHIP_OPTIONS.map(opt => (
        <button
          key={opt.id}
          onClick={() => setActive(opt.id)}
          className={`h-7 px-2.5 rounded-full text-[11.5px] font-medium transition ${
            active === opt.id
              ? 'bg-slate-900 text-white'
              : 'bg-slate-100 text-slate-500 hover:bg-slate-200 hover:text-slate-800'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

// ── Status filter tabs ────────────────────────────────────────────────────────

type StatusFilter = 'all' | JobStatus

const STATUS_TABS: { id: StatusFilter; label: string }[] = [
  { id: 'all',     label: 'All'     },
  { id: 'new',     label: 'New'     },
  { id: 'saved',   label: 'Saved'   },
  { id: 'applied', label: 'Applied' },
  { id: 'ignored', label: 'Skipped' },
]

// ── Sort toggle ───────────────────────────────────────────────────────────────

type SortBy = 'score' | 'date'

function SortToggle({ value, onChange }: { value: SortBy; onChange: (v: SortBy) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-full border border-slate-200 p-0.5 bg-white text-[11.5px]">
      {(['score', 'date'] as SortBy[]).map(v => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={`h-6 px-2.5 rounded-full font-medium transition ${
            value === v
              ? 'bg-slate-900 text-white'
              : 'text-slate-500 hover:text-slate-800'
          }`}
        >
          {v === 'score' ? 'ATS Score' : 'Newest'}
        </button>
      ))}
    </div>
  )
}

// ── Top Fits toggle ───────────────────────────────────────────────────────────

const TOP_FITS_THRESHOLD = 60.0

function TopFitsToggle({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      title={active ? 'Showing top fits only (ATS score > 60)' : 'Show all scores'}
      className={`inline-flex items-center gap-1.5 h-7 px-3 rounded-full text-[11.5px] font-semibold transition ${
        active
          ? 'bg-emerald-600 text-white shadow-sm'
          : 'bg-slate-100 text-slate-500 hover:bg-slate-200 hover:text-slate-800'
      }`}
    >
      {active ? '✦' : '◇'} Top Fits
    </button>
  )
}

// ── JobFeed ───────────────────────────────────────────────────────────────────

interface JobFeedProps {
  /**
   * Called after a Force Refresh completes so the parent (page.tsx) can
   * re-fetch the Overview stats from the same data pool.
   */
  onFeedRefreshed?: () => void
  /**
   * Current user preferences — used to filter the Matches feed.
   * Analytics is untouched; only this component reads preferences.
   */
  preferences?: AutomationSettings
  /**
   * job_id to auto-expand on first render — set when the user clicks a
   * Top Matches row on the Overview tab.
   */
  expandJobId?: string
  /** Passed to each JobCard to enable Ariel Insight probes. */
  userId?: string
}

export function JobFeed({ onFeedRefreshed, preferences, expandJobId, userId }: JobFeedProps = {}) {
  const [jobs,         setJobs]         = useState<ApiFeedJob[]>([])
  // Raw count before the zero-click completeness filter — distinguishes
  // "pipeline still running" (totalFetched > 0, jobs === 0) from
  // "genuinely no rows yet" (totalFetched === 0).
  const [totalFetched, setTotalFetched] = useState(-1)  // -1 = not yet loaded
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState('')
  const [status,     setStatus]     = useState<StatusFilter>('all')
  const [search,     setSearch]     = useState('')
  const [source,     setSource]     = useState<SourceFilter>('all')
  const [sortBy,     setSortBy]     = useState<SortBy>('score')
  const [topFitsOnly,setTopFitsOnly]= useState(false)
  const [pageEnd,    setPageEnd]    = useState(PAGE_SIZE)
  const [syncing,          setSyncing]          = useState(false)
  const [jobUrl,           setJobUrl]           = useState('')
  const [isAnalyzing,      setIsAnalyzing]      = useState(false)
  const [toast,            setToast]            = useState<{ message: string; tone: 'success' | 'error' } | null>(null)
  const [reviewJob,        setReviewJob]        = useState<{ feedJob: ApiFeedJob; job: Job } | null>(null)
  // Tracks the job_id returned by handleAnalyze so the card auto-expands on insert
  const [freshExpandId,    setFreshExpandId]    = useState<string | undefined>(undefined)

  // ── Interaction lock ────────────────────────────────────────────────────────
  // While any card is expanded or mid-fetch the list order is frozen so the
  // card stays in its visual position even after a score update.
  const [activeJobIds,      setActiveJobIds]      = useState<ReadonlySet<string>>(new Set())
  const [lockedOrder,       setLockedOrder]       = useState<string[] | null>(null)
  // Jobs whose score dropped below TOP_FITS_THRESHOLD while the card was open.
  // They remain visible (with a badge) until the next manual loadJobs().
  const [belowThresholdIds, setBelowThresholdIds] = useState<ReadonlySet<string>>(new Set())

  const sortLocked = activeJobIds.size > 0

  // Dismiss toast after 5 s — long enough to read rescore/backfill messages
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(t)
  }, [toast])

  const loadJobs = useCallback(async () => {
    setLoading(true)
    setError('')
    // Release any frozen order and threshold exceptions on every full reload
    setLockedOrder(null)
    setBelowThresholdIds(new Set())
    try {
      // Refresh the module-level auth token from the live Supabase session
      // before every fetch.  The token is a module-level variable in api.ts;
      // if AuthContext hasn't set it yet (cold mount race) the request would
      // go unauthenticated → 401 → _onAuthError → signOut → localStorage.clear()
      // → tab resets to 'overview'.  This one-liner closes that race window.
      if (supabase) {
        const { data: { session } } = await supabase.auth.getSession()
        if (session?.access_token) setAuthToken(session.access_token)
      }

      const data = await fetchFeedJobs(undefined, 100, {
        minScore: preferences?.minScore,
      })
      setTotalFetched(data.length)
      // Zero-Click contract: only render jobs that are fully processed.
      // Incomplete rows (missing title, company, score, or structured JD) are
      // pipeline artefacts that should never surface to the user.
      const complete = data.filter(j =>
        j.title?.trim() &&
        j.company?.trim() &&
        (j.match_score ?? 0) > 0 &&
        j.jd_structured?.trim()
      )
      setJobs(complete)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load jobs.')
    } finally {
      setLoading(false)
    }
  }, [preferences?.minScore])

  // Initial mount only — loadJobs is NOT in the dependency array intentionally.
  // Putting loadJobs here would re-fire on every preferences change because
  // useCallback recreates it, causing an infinite request loop.
  // Subsequent loads are explicit: Refresh button (handleSync) or user action.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadJobs() }, [])

  // Reset page when any filter changes
  useEffect(() => { setPageEnd(PAGE_SIZE) }, [status, search, source, sortBy, topFitsOnly])

  // Unified sync — manual trigger only (Sync Data button).
  // Step 1: backfill missing JDs. Step 2: rescore. Step 3: reload feed.
  // No setTimeout, no automatic re-triggers.
  const handleSync = useCallback(async () => {
    setSyncing(true)
    // Clear the current list immediately so the user sees a loading skeleton
    // instead of the old stale snapshot while the sync is in flight.
    setJobs([])
    setTotalFetched(-1)
    setLoading(true)
    try {
      // Same token-refresh guard as loadJobs — Sync Data can be clicked any
      // time, including right after login before the token has settled.
      if (supabase) {
        const { data: { session } } = await supabase.auth.getSession()
        if (session?.access_token) setAuthToken(session.access_token)
      }
      const res = await backfillJdText(50.0)
      const n   = res.queued
      await forceRefreshAllScores()
      await loadJobs()
      onFeedRefreshed?.()
      setToast({
        message: n > 0
          ? `Synced ${n} job description${n !== 1 ? 's' : ''} and re-scored all jobs.`
          : 'Re-scored all jobs against your latest profile.',
        tone: 'success',
      })
    } catch {
      setToast({ message: 'Sync failed. Please try again.', tone: 'error' })
    } finally {
      setSyncing(false)
    }
  }, [loadJobs, onFeedRefreshed])

  /**
   * Submit a single job URL for the Zero-Click blocking pipeline.
   *
   * POST /api/jobs/analyze blocks until scrape → structure → score completes,
   * then returns the fully-processed JobMatch.  The job is prepended directly
   * into local state — no loadJobs() call, no polling.
   */
  const handleAnalyze = useCallback(async () => {
    const url = jobUrl.trim()
    if (!url) return
    setIsAnalyzing(true)
    try {
      // POST /api/jobs/analyze blocks until fully processed and returns the
      // complete JobMatch (same shape as ApiFeedJob).  Prepend it directly
      // into local state — no re-fetch of the entire feed needed.
      const newJob = await startAnalysis(url)
      setJobUrl('')
      setJobs(prev => {
        // Guard against the cache-hit case returning a duplicate.
        const already = prev.some(j => j.job_id === newJob.job_id)
        return already ? prev : [newJob, ...prev]
      })
      // Auto-expand the new card so the user sees the analysis immediately.
      setFreshExpandId(newJob.job_id)
      setToast({ message: `"${newJob.title}" added to your feed (ATS ${newJob.match_score.toFixed(1)})`, tone: 'success' })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Analysis failed.'
      setToast({ message: msg, tone: 'error' })
    } finally {
      setIsAnalyzing(false)
    }
  }, [jobUrl])

  const handleSkip = useCallback(async (id: string) => {
    setJobs(prev => prev.map(j => j.job_id === id ? { ...j, status: 'ignored' } : j))
    try {
      await updateJobStatus(id, 'ignored')
    } catch {
      setJobs(prev => prev.map(j => j.job_id === id ? { ...j, status: 'new' } : j))
      setToast({ message: 'Could not skip job. Please try again.', tone: 'error' })
    }
  }, [])

  const handleSave = useCallback(async (id: string) => {
    const job       = jobs.find(j => j.job_id === id)
    const nextStatus: JobStatus = job?.status === 'saved' ? 'new' : 'saved'
    setJobs(prev => prev.map(j => j.job_id === id ? { ...j, status: nextStatus } : j))
    try {
      await updateJobStatus(id, nextStatus)
    } catch {
      const prevStatus = job?.status ?? 'new'
      setJobs(prev => prev.map(j => j.job_id === id ? { ...j, status: prevStatus as JobStatus } : j))
      setToast({ message: 'Could not update job. Please try again.', tone: 'error' })
    }
  }, [jobs])

  const handleTailorCV = useCallback((feedJob: ApiFeedJob) => {
    // Always re-read from jobs state rather than using the prop snapshot that
    // JobCard held at render time — guarantees the guard below sees the latest
    // status and jd_structured values, not a stale closure capture.
    const fresh = jobs.find(j => j.job_id === feedJob.job_id) ?? feedJob
    const rank  = jobs.findIndex(j => j.job_id === feedJob.job_id)

    const pipelineDone =
      (fresh.status === 'new' || fresh.score_is_proxy === false) &&
      !!fresh.jd_structured?.trim()

    if (!pipelineDone) {
      // Previously a silent console.warn + return — clicking "Tailor CV" did
      // visibly nothing (JOB-115): no toast, no modal, no explanation. The
      // CV preview's OWN internal guard (ApplierPreview.tsx's handleGenerate)
      // already surfaces this exact situation via setError(), but that guard
      // never gets a chance to run because this outer one decides whether to
      // open the modal at all. Mirror the same message here so the user gets
      // the same explanation regardless of which guard actually catches it.
      console.warn('[JobFeed] CV generation blocked — job not ready',
        { job_id: fresh.job_id, status: fresh.status, score_is_proxy: fresh.score_is_proxy, has_jd: Boolean(fresh.jd_structured) })
      setToast({ message: 'Job details are still loading. Please wait a moment and try again.', tone: 'error' })
      return
    }

    setReviewJob({ feedJob: fresh, job: toJob(fresh, rank) })
  }, [jobs])

  /**
   * Called by each JobCard whenever its expanded/fetch state changes.
   * Drives the sort-lock: while any card is active the list order is frozen.
   */
  const handleInteractionChange = useCallback((jobId: string, active: boolean) => {
    setActiveJobIds(prev => {
      const next = new Set(prev)
      active ? next.add(jobId) : next.delete(jobId)
      return next
    })
  }, [])

  /**
   * Called by JobCard when the user confirms they applied.
   * Updates the local job status to 'applied' so it moves to the correct tab.
   */
  const handleMarkApplied = useCallback((jobId: string) => {
    setJobs(prev => prev.map(j =>
      j.job_id === jobId ? { ...j, status: 'applied' as const } : j
    ))
    setToast({ message: '✓ Marked as Applied. Visible in Applications board', tone: 'success' })
  }, [])

  // ── Local filtering + sorting (no extra API calls) ────────────────────────

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()

    let result = jobs.filter(j => {
      // Status tab
      if (status === 'all' && j.status === 'ignored') return false
      if (status !== 'all' && j.status !== status)   return false
      // Source chip
      if (source !== 'all' && j.source_type !== source) return false
      // Top Fits toggle — only show jobs with ATS score above threshold
      if (topFitsOnly && j.match_score <= TOP_FITS_THRESHOLD) return false
      // Text search on title + company
      if (q && !j.title.toLowerCase().includes(q) && !j.company.toLowerCase().includes(q)) return false
      // ── User preferences (Matches page only) ─────────────────────────────
      // min_score is already applied server-side; replicated here as safety net
      // work_modes, regions, company_stages are client-side keyword heuristics
      if (preferences && !passesPreferences(j, preferences)) return false
      return true
    })

    // Sort — always by match_score (LLM composite); never fall back to the
    // stale `score` column which holds the old MatcherAgent fit score.
    if (sortBy === 'score') {
      result = [...result].sort((a, b) => b.match_score - a.match_score)
    } else {
      // "Newest" — primary key is created_at ISO string; fall back to job_id
      // (lexicographically descending) for rows where created_at is null so
      // the sort is never a no-op on partially-populated feeds.
      result = [...result].sort((a, b) => {
        const ta = a.created_at ?? a.job_id
        const tb = b.created_at ?? b.job_id
        return tb.localeCompare(ta)
      })
    }

    return result
  }, [jobs, status, source, search, sortBy, topFitsOnly, preferences])

  // ── Sort-lock: capture / release frozen order ─────────────────────────────
  // Capture the current sorted order the moment the first card opens.
  // Release it when all cards close (sortLocked → false).
  useEffect(() => {
    if (sortLocked && lockedOrder === null) {
      // First card opened — freeze the current visible order
      setLockedOrder(filtered.map(j => j.job_id))
    } else if (!sortLocked && lockedOrder !== null) {
      // Last card closed — release the frozen order
      setLockedOrder(null)
    }
  // filtered intentionally excluded: we only want to capture at the transition,
  // not re-capture on every data update.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortLocked])

  // ── displayList: frozen-order list for rendering ─────────────────────────
  // When locked: reorder jobs by lockedOrder (positions stay, data stays fresh).
  // Below-threshold exceptions bypass the TopFits gate until next reload.
  // When unlocked: identical to filtered.
  const displayList = useMemo(() => {
    if (!lockedOrder) return filtered

    const jobById = new Map(jobs.map(j => [j.job_id, j]))
    const q       = search.trim().toLowerCase()

    return lockedOrder
      .map(id => jobById.get(id))
      .filter((j): j is ApiFeedJob => {
        if (!j) return false
        // Re-apply all filters — but TopFits gate honours the below-threshold exception set
        if (status === 'all' && j.status === 'ignored') return false
        if (status !== 'all' && j.status !== status)   return false
        if (source !== 'all' && j.source_type !== source) return false
        if (topFitsOnly && j.match_score <= TOP_FITS_THRESHOLD && !belowThresholdIds.has(j.job_id)) return false
        if (q && !j.title.toLowerCase().includes(q) && !j.company.toLowerCase().includes(q)) return false
        return true
      })
  }, [lockedOrder, filtered, jobs, status, source, search, topFitsOnly, belowThresholdIds])

  const visible     = displayList.slice(0, pageEnd)
  const hasMore     = displayList.length > pageEnd
  const totalShown  = visible.length

  return (
    <section className="w-full">
      <div className="max-w-4xl space-y-8">

        {/* ── Page heading + sync ───────────────────────────────────────────── */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">Top Matches for You</h1>
            <p className="text-sm text-slate-400 mt-1">
              Jobs scored against your profile and sorted by ATS match.
            </p>
          </div>
          <button
            onClick={handleSync}
            disabled={syncing || loading}
            title="Fetch missing job descriptions and re-score all jobs against your latest profile"
            className="shrink-0 inline-flex items-center gap-2 h-9 px-4 rounded-lg text-[13px] font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 transition active:scale-[0.97] disabled:opacity-50 disabled:pointer-events-none"
          >
            {syncing ? <Spinner /> : (
              <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="23 4 23 10 17 10" />
                <polyline points="1 20 1 14 7 14" />
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
              </svg>
            )}
            {syncing ? 'Syncing…' : 'Sync Data'}
          </button>
        </div>

        {/* ── URL submission bar ────────────────────────────────────────────── */}
        <form onSubmit={e => { e.preventDefault(); handleAnalyze() }} className="flex gap-2">
          <input
            type="url"
            placeholder="Paste a job URL to analyse…"
            value={jobUrl}
            onChange={e => setJobUrl(e.target.value)}
            disabled={isAnalyzing}
            className="flex-1 h-9 px-3 rounded-lg border border-slate-200 bg-white text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-400 transition disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={isAnalyzing || !jobUrl.trim()}
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg text-[13px] font-medium text-white transition active:scale-[0.97] disabled:opacity-50 disabled:pointer-events-none"
            style={{ background: isAnalyzing ? '#94a3b8' : TOKENS.color.primary }}
          >
            {isAnalyzing ? <><Spinner size={13} /> Analysing…</> : 'Analyse'}
          </button>
        </form>

        {/* ── Filters row ───────────────────────────────────────────────────── */}
        <div className="flex flex-col sm:flex-row gap-2.5">
          <div className="flex-1 min-w-0">
            <SearchBar value={search} onChange={setSearch} />
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <SourceChips active={source} setActive={setSource} />
            <div className="h-5 w-px bg-slate-200 hidden sm:block" />
            <TopFitsToggle active={topFitsOnly} onToggle={() => setTopFitsOnly(v => !v)} />
          </div>
        </div>

        {/* ── Error banner ──────────────────────────────────────────────────── */}
        {error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 flex items-center justify-between">
            <p className="text-[13px] text-rose-700">
              <span className="font-medium">Could not load feed</span>
              <span className="text-rose-500">: {error}</span>
            </p>
            <button onClick={loadJobs} className="text-[12px] font-medium text-rose-700 underline underline-offset-2">
              Retry
            </button>
          </div>
        )}

        {/* ── Status tabs + sort + count ────────────────────────────────────── */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-4 text-sm font-medium text-slate-400">
            {STATUS_TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setStatus(t.id)}
                className={`pb-1 transition-colors ${
                  status === t.id
                    ? 'text-slate-900 border-b-2 border-slate-900'
                    : 'hover:text-slate-900'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <span className="text-[12px] text-slate-400 tabular-nums">
              {totalShown} of {displayList.length}
              {sortLocked && (
                <span
                  className="ml-1.5 inline-flex items-center gap-0.5 text-[10.5px] text-amber-600 font-medium"
                  title="Sort order is paused while a card is open."
                >
                  <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  Sort paused
                </span>
              )}
            </span>
            <SortToggle value={sortBy} onChange={v => { if (!sortLocked) setSortBy(v) }} />
          </div>
        </div>

        {/* ── Job list ──────────────────────────────────────────────────────── */}
        {loading ? (
          <div className="space-y-8">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="bg-white rounded-2xl border border-slate-100 p-8"
                style={{
                  opacity: 1 - i * 0.18,
                  boxShadow: '0 2px 8px rgba(0,0,0,0.02), 0 20px 40px rgba(0,0,0,0.03)',
                }}
              >
                <div className="flex justify-between items-start mb-6">
                  <div className="space-y-2 flex-1 pr-8">
                    <div className="h-5 w-64 rounded-lg bg-slate-100 animate-pulse" />
                    <div className="h-3.5 w-40 rounded bg-slate-100 animate-pulse" />
                  </div>
                  <div className="h-9 w-16 rounded-lg bg-slate-100 animate-pulse shrink-0" />
                </div>
                <div className="space-y-2 mb-8">
                  <div className="h-3.5 w-full rounded bg-slate-100 animate-pulse" />
                  <div className="h-3.5 w-4/5 rounded bg-slate-100 animate-pulse" />
                </div>
                <div className="flex gap-3">
                  <div className="h-11 w-28 rounded-lg bg-slate-100 animate-pulse" />
                  <div className="h-11 w-40 rounded-lg bg-slate-100 animate-pulse" />
                </div>
              </div>
            ))}
          </div>
        ) : visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 gap-2 text-slate-400">
            {/* Pipeline-indexing state: rows exist in DB but none are pipeline-complete yet */}
            {!search && !topFitsOnly && status === 'all' && jobs.length === 0 && totalFetched > 0 ? (
              <>
                <div className="flex items-center gap-2 mb-1">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                    stroke="#0D9488" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                    style={{ animation: 'spin 1.4s linear infinite' }}
                  >
                    <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
                    <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                  </svg>
                  <span className="text-[13px] font-semibold text-teal-700">Agents are actively indexing fresh roles</span>
                </div>
                <p className="text-[12.5px] text-center text-slate-500 max-w-xs">
                  {totalFetched} job{totalFetched !== 1 ? 's' : ''} found in the pipeline.
                  Scoring and JD enrichment in progress. Results will appear here automatically.
                </p>
                <button
                  onClick={handleSync}
                  disabled={syncing}
                  className="mt-3 inline-flex items-center gap-1.5 h-8 px-4 rounded-lg text-[12px] font-medium border border-teal-200 bg-teal-50 text-teal-700 hover:bg-teal-100 transition disabled:opacity-50"
                >
                  {syncing ? <Spinner size={12} /> : null}
                  {syncing ? 'Syncing…' : 'Check for updates'}
                </button>
              </>
            ) : !search && !topFitsOnly && status === 'all' && totalFetched === 0 ? (
              /* Genuinely empty DB — no jobs at all yet */
              <>
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
                  className="text-slate-300"
                >
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  <line x1="8" y1="11" x2="14" y2="11" />
                </svg>
                <p className="text-[14px] font-medium text-slate-600">No jobs discovered yet</p>
                <p className="text-[13px] text-center text-slate-500 max-w-xs">
                  Agents are warming up. New roles will appear here once the first scraping cycle completes.
                </p>
              </>
            ) : (
              /* Filter returned nothing */
              <>
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
                  className="text-slate-300"
                >
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  <line x1="8" y1="11" x2="14" y2="11" />
                </svg>
                <p className="text-[14px] font-medium text-slate-600">No jobs found</p>
                <p className="text-[13px] text-center">
                  {search
                    ? `No results for "${search}". Try a different search term.`
                    : topFitsOnly
                      ? `No matches with ATS score above ${TOP_FITS_THRESHOLD}. Try disabling Top Fits.`
                      : `No jobs with status "${status}".`}
                </p>
              </>
            )}
            {(search || topFitsOnly) && (
              <div className="mt-2 flex items-center gap-3">
                {search && (
                  <button onClick={() => setSearch('')} className="text-[12.5px] font-medium text-teal-600 hover:underline">
                    Clear search
                  </button>
                )}
                {topFitsOnly && (
                  <button onClick={() => setTopFitsOnly(false)} className="text-[12.5px] font-medium text-teal-700 hover:underline">
                    Show all scores
                  </button>
                )}
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="space-y-8">
              {visible.map(j => (
                <JobCard
                  key={j.job_id}
                  job={j}
                  userId={userId}
                  isTopFit={j.match_score > TOP_FITS_THRESHOLD}
                  belowThreshold={belowThresholdIds.has(j.job_id)}
                  initialExpanded={expandJobId === j.job_id || freshExpandId === j.job_id}
                  onSkip={handleSkip}
                  onSave={handleSave}
                  onTailorCV={handleTailorCV}
                  onInteractionChange={handleInteractionChange}
                  onMarkApplied={handleMarkApplied}
                />
              ))}
            </div>

            {hasMore && (
              <div className="flex justify-center">
                <button
                  onClick={() => setPageEnd(p => p + PAGE_SIZE)}
                  className="inline-flex items-center gap-2 h-9 px-6 rounded-lg text-[13px] font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 transition active:scale-[0.97]"
                >
                  Load more
                  <span className="text-slate-400 tabular-nums text-[12px]">
                    +{Math.min(PAGE_SIZE, filtered.length - pageEnd)}
                  </span>
                </button>
              </div>
            )}
          </>
        )}

      </div>

      {/* Full CV PDF editor */}
      {reviewJob && (
        <ApplierPreview
          job={reviewJob.job}
          feedJob={reviewJob.feedJob}
          onClose={() => setReviewJob(null)}
          onApplied={id => {
            handleSave(id)
            setReviewJob(null)
          }}
        />
      )}

      {toast && <Toast message={toast.message} tone={toast.tone} />}
    </section>
  )
}
