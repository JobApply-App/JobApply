'use client'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useI18n } from '@/contexts/I18nContext'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { DEFAULT_SETTINGS, type AutomationSettings } from '@/lib/data'
import { useAgentStatus }       from '@/hooks/useAgentStatus'
import { useJobMatches }        from '@/hooks/useJobMatches'
import { Header }               from '@/components/Header'
import type { Tab }             from '@/components/Header'
import { Footer }               from '@/components/Footer'
import { ControlsSheet }        from '@/components/ControlsSheet'
import { Overview }             from '@/components/Overview'
import { JobFeed }              from '@/components/JobFeed'
import { ApplicationsTab }      from '@/components/ApplicationsTab'
import { AgentStatusCenter }    from '@/components/AgentStatusCenter'
import { ApplierPreview }       from '@/components/ApplierPreview'
import AuthGuard                from '@/components/AuthGuard'
import { useAuth }              from '@/contexts/AuthContext'
import { resolveDisplayName }   from '@/lib/nameUtils'
import type { Job }             from '@/lib/data'
import type { ApiFeedJob }      from '@/lib/apiTypes'
import { TOKENS }               from '@/lib/tokens'

// ── Identity-sync gate ────────────────────────────────────────────────────────
//
// PURPOSE
//   On first login, sync the Supabase identity with the backend (account
//   linking by verified email, profile_completed backfill) before the
//   dashboard's data hooks mount.
//
// DESIGN — render gate, not background hook
//   SyncGate renders a brief blocking screen until sync-user responds (or a
//   locally-cached flag says it already ran). HomePageContent (and every hook
//   inside it) only mounts AFTER the gate transitions to 'done', so the very
//   first data fetch already sees the correctly-linked user_id.
//
// STATES
//   idle      — user/session not yet available (should be instant; AuthGuard
//               guarantees children only render with a confirmed session)
//   in_flight — POST in progress → show blocking spinner + message
//   done      — sync attempted (success or failure — sync-user is best-effort
//               and non-fatal) → render children
//
// NOTE — legacy data migration removed from this flow
//   POST /api/auth/migrate-legacy-data used to fire here for every user. It
//   is now an admin-only, one-time utility (see backend/api/routes/auth.py)
//   rather than a normal login action, so it is no longer called from the
//   dashboard entry gate. A failed or admin-gated migration must never block
//   a normal user from reaching the dashboard.
//
// IDEMPOTENCY
//   localStorage key `jobapply_synced_{userId}` is set once sync-user has
//   run for this user in this browser, so subsequent visits skip the
//   network call entirely and go straight to done.

type MigrationPhase = 'idle' | 'in_flight' | 'done'

function MigrationGate({ children }: { children: React.ReactNode }) {
  const { user, session, updateUserMeta } = useAuth()
  const [phase, setPhase] = useState<MigrationPhase>('idle')
  const firedRef = useRef(false)   // guards against React StrictMode double-invoke

  useEffect(() => {
    // AuthGuard guarantees user is non-null, but session.access_token may settle
    // one tick after the first render on a cold mount — wait for both.
    if (!user?.id || !session?.access_token) return
    if (firedRef.current) return

    const token      = session.access_token   // capture; won't change mid-request
    const storageKey = `jobapply_synced_${user.id}`

    // ── Fast path: flag already set in this browser ───────────────────────────
    if (localStorage.getItem(storageKey)) {
      // Non-blocking backfill for pre-Phase-8 accounts: if user metadata lacks
      // profile_completed but the backend says the profile has real data, set
      // the flag so Ariel stays available for existing users.
      const metaFlag = (user.user_metadata as Record<string, unknown> | null)?.profile_completed
      if (metaFlag !== true) {
        fetch('/api/auth/sync-user', {
          method:  'POST',
          headers: { 'Authorization': `Bearer ${token}` },
        })
          .then(r => (r.ok ? r.json() : null))
          .then((sync: { profile_completed?: boolean } | null) => {
            if (sync?.profile_completed) {
              void updateUserMeta({ profile_completed: true }).catch(() => { /* retried next visit */ })
            }
          })
          .catch(() => { /* non-fatal */ })
      }
      setPhase('done')
      return
    }

    // ── Slow path: sync identity, then let the dashboard mount ────────────────
    firedRef.current = true
    setPhase('in_flight')

    // Provider-agnostic identity sync (account linking by verified email): if
    // this login minted a new Supabase user for an email that already owns
    // data (e.g. Google OAuth after email signup), the backend re-links all
    // rows to this user_id before anything else reads them. Best-effort and
    // non-fatal — a sync-user failure must never block normal login.
    fetch('/api/auth/sync-user', {
      method:  'POST',
      headers: { 'Authorization': `Bearer ${token}` },
    })
      .then(r => (r.ok ? r.json() : null))
      .then((sync: { status?: string; linked_from?: string; profile_completed?: boolean } | null) => {
        if (sync?.status === 'linked') {
          console.info('[sync-user] account linked from', sync.linked_from)
        }
        // Backfill for accounts created before the profile_completed flag:
        // the backend reports whether the master profile already has real
        // data — mirror that into Supabase user metadata so Ariel unlocks.
        const metaFlag = (user.user_metadata as Record<string, unknown> | null)?.profile_completed
        if (sync?.profile_completed && metaFlag !== true) {
          void updateUserMeta({ profile_completed: true }).catch(() => { /* retried next login */ })
        }
      })
      .catch(() => { /* non-fatal */ })
      .then(() => {
        localStorage.setItem(storageKey, '1')
        setPhase('done')
      })
  }, [user, session])

  // ── Blocking screen (idle / in_flight) ────────────────────────────────────
  if (phase !== 'done') {
    return (
      <div
        className="min-h-screen flex flex-col items-center justify-center gap-5 px-6 bg-ja-ink"
      >
        <div className="w-9 h-9 rounded-full border-2 border-slate-700 border-t-blue-500 animate-spin" />

        {phase === 'in_flight' && (
          <p className="text-sm text-center leading-relaxed text-ja-subtle" style={{ maxWidth: 300 }}>
            Securing your workspace and activating agents…
            <br />
            <span>Please wait.</span>
          </p>
        )}
      </div>
    )
  }

  return <>{children}</>
}

// ── Preferences & navigation helpers ─────────────────────────────────────────

const VALID_TABS: Tab[] = ['overview', 'feed', 'apps']
const LS_KEY     = 'jobapply_prefs'
const LS_TAB_KEY = 'jobapply_active_tab'

function loadPrefs(): AutomationSettings {
  if (typeof window === 'undefined') return DEFAULT_SETTINGS
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) }
  } catch { /* corrupt — fall back to defaults */ }
  return DEFAULT_SETTINGS
}

/**
 * Read the last-active tab from localStorage.
 * Falls back to 'overview' if nothing is stored, the value is invalid,
 * or localStorage is unavailable (SSR / private-browsing quota error).
 */
function loadSavedTab(): Tab {
  if (typeof window === 'undefined') return 'overview'
  try {
    const saved = localStorage.getItem(LS_TAB_KEY)
    if (saved && (VALID_TABS as string[]).includes(saved)) return saved as Tab
  } catch { /* storage unavailable */ }
  return 'overview'
}

// ── Main dashboard content ────────────────────────────────────────────────────
//
// Only mounts after MigrationGate confirms the migration is complete.
// Every hook and data fetch inside here therefore starts with migrated data
// already committed to the database under the correct user_id.

function HomePageContent() {
  const { user } = useAuth()
  const router    = useRouter()
  const displayName = resolveDisplayName(
    user?.email,
    user?.user_metadata as Record<string, unknown> | null,
  )

  const searchParams = useSearchParams()

  // Tab resolution priority:
  //   1. ?tab=<value> URL param  — lets deep-links and cross-page navigation
  //      (e.g. from Analytics) land on the correct tab.
  //   2. localStorage             — restores the user's last view on hard refresh
  //      (F5 / Ctrl+R) when the URL carries no tab param.
  //   3. 'overview'               — safe default for brand-new sessions.
  const urlTab     = searchParams.get('tab') as Tab | null
  const initialTab = (urlTab && VALID_TABS.includes(urlTab)) ? urlTab : loadSavedTab()
  const [tab,          setTab]          = useState<Tab>(initialTab)
  const [savedIds,     setSavedIds]     = useState<string[]>([])
  const [dismissedIds, setDismissedIds] = useState<string[]>([])
  const [controlsOpen, setControlsOpen] = useState(false)
  const [settings,     setSettings]     = useState<AutomationSettings>(loadPrefs)
  const [reviewJob,    setReviewJob]    = useState<{ job: Job; feedJob: ApiFeedJob } | null>(null)
  // Bumped each time a job is manually analyzed — forces JobFeed to remount and re-fetch
  const [feedKey,      setFeedKey]      = useState(0)
  // job_id to auto-expand when switching to the feed tab from a Top Matches click
  const [expandJobId,  setExpandJobId]  = useState<string | undefined>(undefined)
  // Jobs analyzed manually on the Overview tab, merged into stats until next feed load
  const [manualFeedJobs, setManualFeedJobs] = useState<ApiFeedJob[]>([])

  // ── Persist active tab so hard refreshes restore the current view ───────────
  useEffect(() => {
    try { localStorage.setItem(LS_TAB_KEY, tab) } catch { /* storage quota */ }
  }, [tab])

  // ── Persist preferences whenever they change ────────────────────────────────
  useEffect(() => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(settings)) } catch { /* quota */ }
  }, [settings])

  // ── Live data ───────────────────────────────────────────────────────────────
  const { agents, loading: agentsLoading, error: agentsError, refetch: retryAgents } = useAgentStatus()
  const { jobs: rawJobs, feedJobs, loading: jobsLoading } = useJobMatches()

  // Merge manually-analyzed jobs with hook-fetched data so stats stay live.
  // Memoized: these were previously recomputed via IIFE on every render of
  // this top-level component (e.g. every tab click via setTab), even though
  // switching tabs never changes the underlying job data — a real source of
  // input lag on nav clicks once the job list is non-trivial in size.
  const allFeedJobs = useMemo(() => {
    const ids = new Set(feedJobs.map(f => f.job_id))
    return [...manualFeedJobs.filter(j => !ids.has(j.job_id)), ...feedJobs]
  }, [feedJobs, manualFeedJobs])

  const allRawJobs = useMemo(() => {
    const ids = new Set(rawJobs.map(j => j.id))
    return [
      ...manualFeedJobs.filter(j => !ids.has(j.job_id)).map((f, i) => ({
        id:         f.job_id,
        title:      f.title,
        company:    f.company,
        location:   f.location,
        postedAt:   f.posted_at,
        postedRank: i,
        score:      f.match_score,
        isNew:      f.is_new,
        reasons:    f.reasons,
        whyRon:     f.why_ron ?? null,
      })),
      ...rawJobs,
    ]
  }, [rawJobs, manualFeedJobs])

  // Local mutations applied on top of the live job list
  const jobs = useMemo(
    () => allRawJobs.filter(j => !dismissedIds.includes(j.id)),
    [allRawJobs, dismissedIds],
  )

  // ── Interaction handlers ────────────────────────────────────────────────────
  const onApply   = (id: string) => {
    setDismissedIds(prev => [...prev, id])
    setSavedIds(prev => prev.filter(s => s !== id))
  }
  const onSave    = (id: string) =>
    setSavedIds(prev => prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id])
  const onDismiss = (id: string) => setDismissedIds(prev => [...prev, id])
  const onReviewCV = (id: string) => {
    const job     = jobs.find(j => j.id === id)
    const feedJob = allFeedJobs.find(f => f.job_id === id)
    if (job && feedJob) setReviewJob({ job, feedJob })
  }

  // Called by AgentStatusCenter when a job is successfully analyzed
  const handleJobAnalyzed = (feedJob: ApiFeedJob) => {
    setManualFeedJobs(prev =>
      prev.some(j => j.job_id === feedJob.job_id) ? prev : [feedJob, ...prev]
    )
    // Force JobFeed to remount so it re-fetches and includes the new job
    setFeedKey(k => k + 1)
  }

  // Called when the user clicks "Tailor CV" on the inline analysis result card
  const handleTailorCVFromOverview = (feedJob: ApiFeedJob) => {
    const job = jobs.find(j => j.id === feedJob.job_id) ?? {
      id:         feedJob.job_id,
      title:      feedJob.title,
      company:    feedJob.company,
      location:   feedJob.location,
      postedAt:   feedJob.posted_at,
      postedRank: 0,
      score:      feedJob.match_score,
      isNew:      feedJob.is_new,
      reasons:    feedJob.reasons,
      whyRon:     feedJob.why_ron ?? null,
    }
    setReviewJob({ job, feedJob })
  }
  const onGo = (t: string, jobId?: string) => {
    if (t === 'prefs')                          setControlsOpen(true)
    else if (t === 'profile-builder')           router.push('/profile-builder?forceIntro=true')
    else if (t === 'profile-builder:optimize_gaps') router.push('/profile-builder?intent=optimize_gaps&forceIntro=true')
    else {
      // When a specific job is requested, store its id so JobFeed can auto-expand it.
      // Clear after the first render by not re-using the same feedKey.
      if (jobId) setExpandJobId(jobId)
      else       setExpandJobId(undefined)
      setTab(t as Tab)
    }
  }

  // Jobs scanned today = new + manually analyzed jobs
  const jobsScannedToday = jobs.filter(j => j.isNew).length + manualFeedJobs.length

  return (
    <div className="min-h-screen flex flex-col bg-ja-bg">
      <Header tab={tab} setTab={setTab} onOpenControls={() => setControlsOpen(true)} jobs={jobs} />

      <main className="flex-grow max-w-content mx-auto w-full px-6 py-8">
        {tab === 'overview' && (
          <div className="space-y-10">
            <Overview
              userId={user?.id ?? ''}
              jobsScannedToday={jobsScannedToday}
              feedJobs={allFeedJobs}
              jobsLoading={jobsLoading}
              savedIds={savedIds}
              displayName={displayName}
              onSave={onSave} onReviewCV={onReviewCV} onGo={onGo}
            />
            <AgentStatusCenter
              agents={agents}
              loading={agentsLoading}
              error={agentsError}
              onRetry={retryAgents}
              onJobAnalyzed={handleJobAnalyzed}
              onTailorCV={handleTailorCVFromOverview}
            />
          </div>
        )}

        {tab === 'feed' && <JobFeed key={feedKey} preferences={settings} expandJobId={expandJobId} userId={user?.id ?? ''} />}

        {tab === 'apps'  && <ApplicationsTab />}
      </main>

      <Footer />

      <ControlsSheet
        open={controlsOpen} onClose={() => setControlsOpen(false)}
        settings={settings}  setSettings={setSettings}
      />

      {reviewJob && (
        <ApplierPreview
          job={reviewJob.job}
          feedJob={reviewJob.feedJob}
          onClose={() => setReviewJob(null)}
          onApplied={id => { onApply(id); setReviewJob(null) }}
        />
      )}
    </div>
  )
}

// ── Landing Page (public, unauthenticated) ────────────────────────────────────

// ── Hero mockup: KPI strip + one job card — mirrors the real Overview + JobCard
// KPIStat: pure typography, no boxes (exactly as Overview.tsx KPIRow renders)
// JobCard row: flat white, border-slate-200, score as plain text-2xl numeral
function ATSMockup() {
  const { t } = useI18n()
  return (
    <div className="mx-auto mt-14 max-w-[560px] space-y-8">

      {/* KPI strip — no boxes, no borders, pure typography from Overview.tsx */}
      <div className="grid grid-cols-3 gap-8 px-2">
        {[
          { label: 'Jobs scanned today', value: '47',  sub: 'New roles discovered by agents', accent: TOKENS.color.primary },
          { label: 'High matches',       value: '12',  sub: 'ATS score above 85',              accent: TOKENS.color.success },
          { label: 'CVs tailored',       value: '3',   sub: 'Analyses run this week',          accent: TOKENS.color.violet  },
        ].map(stat => (
          <div key={stat.label} className="flex flex-col min-w-0">
            <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-slate-400 mb-1">
              {stat.label}
            </span>
            <span className="text-[38px] font-semibold tabular-nums leading-none tracking-tight text-slate-900 mb-1">
              {stat.value}
            </span>
            <span className="text-[12px] text-slate-400 leading-snug mb-3">{stat.sub}</span>
            <span className="block h-[3px] w-8 rounded-full mt-auto" style={{ background: stat.accent }} />
          </div>
        ))}
      </div>

      {/* Single JobCard collapsed row — flat white, border-slate-200, thin card shadow */}
      <article
        className="bg-white rounded-2xl border border-slate-200 px-6 py-5 flex items-center gap-4"
        style={{ boxShadow: '0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)' }}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h2 className="text-[15px] font-bold text-slate-900 tracking-tight">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full align-middle mr-2 -translate-y-[2px] bg-ja-primary"
              />
              Senior Product Manager
            </h2>
            <span className="bg-teal-50 text-teal-700 text-[11px] font-semibold px-2 py-0.5 rounded-lg ring-1 ring-inset ring-teal-600/20 shrink-0">
              {t.mockup.strong_match}
            </span>
          </div>
          <p className="text-[12.5px] text-slate-400 mt-1">Wix · Tel Aviv · 2d ago</p>
        </div>
        <div className="flex items-baseline gap-0.5 shrink-0">
          <span className="text-2xl font-bold text-slate-900 tracking-tight tabular-nums">88.0</span>
          <span className="text-[10px] font-semibold text-slate-400 ml-0.5">/100</span>
        </div>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
          className="shrink-0 text-slate-300">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </article>

    </div>
  )
}

// ── FeedMockup: three flat JobCard collapsed rows — exact real component style
// Flat white cards, border-slate-200, TOKENS.shadow.card, score as plain numeral
function FeedMockup() {
  const { t } = useI18n()
  const items = [
    { title: 'Head of Product',    co: 'Monday.com', loc: 'Tel Aviv', score: 91.2, isNew: true,  strong: true  },
    { title: 'Senior PM — Growth', co: 'Fiverr',     loc: 'Remote',   score: 84.0, isNew: true,  strong: true  },
    { title: 'Product Lead',       co: 'Wix',        loc: 'Tel Aviv', score: 76.5, isNew: false, strong: false },
  ]
  return (
    <div className="space-y-2">
      {items.map(item => (
        <article
          key={item.title}
          className="bg-white rounded-2xl border border-slate-200 px-6 py-5 flex items-center gap-4"
          style={{ boxShadow: '0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)' }}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h3 className="text-[15px] font-bold text-slate-900 tracking-tight">
                {item.isNew && (
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full align-middle mr-2 -translate-y-[2px] bg-ja-primary"
                  />
                )}
                {item.title}
              </h3>
              {item.strong && (
                <span className="bg-teal-50 text-teal-700 text-[11px] font-semibold px-2 py-0.5 rounded-lg ring-1 ring-inset ring-teal-600/20 shrink-0">
                  {t.mockup.strong_match}
                </span>
              )}
            </div>
            <p className="text-[12.5px] text-slate-400 mt-1">{item.co} · {item.loc}</p>
          </div>
          <div className="flex items-baseline gap-0.5 shrink-0">
            <span className="text-2xl font-bold text-slate-900 tracking-tight tabular-nums">
              {item.score.toFixed(1)}
            </span>
            <span className="text-[10px] font-semibold text-slate-400 ml-0.5">/100</span>
          </div>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
            className="shrink-0 text-slate-300">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </article>
      ))}
      <p className="text-[11px] text-center text-slate-400 pt-1">
        {t.mockup.auto_refreshes}
      </p>
    </div>
  )
}

// ── KeywordChipsMockup: exact AtsKeywordsPanel — flat white, thin border,
// coverage bar, amber pills for missing, emerald pills for present
function KeywordChipsMockup() {
  const { t } = useI18n()
  const present = ['Product Strategy', 'OKRs', 'Roadmap', 'B2C', 'Agile', 'Scrum']
  const missing = ['A/B Testing', 'Figma', 'SQL', 'Looker']
  const coverage = Math.round((present.length / (present.length + missing.length)) * 100)
  return (
    <div
      className="rounded-2xl border border-slate-200 bg-white overflow-hidden"
      style={{ boxShadow: '0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)' }}
    >
      {/* Header row with coverage meter */}
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[12.5px] font-semibold text-slate-700">{t.mockup.ats_gap_title}</span>
          <div className="flex items-center gap-1.5">
            <div className="w-24 h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full rounded-full bg-amber-400"
                style={{ width: `${coverage}%` }}
              />
            </div>
            <span className="text-[11px] font-semibold tabular-nums text-amber-600">{coverage}%</span>
          </div>
        </div>
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-slate-400">
          {t.mockup.coverage_label}
        </span>
      </div>
      <div className="px-4 py-4 flex flex-col gap-4">
        {/* Missing keywords */}
        <div>
          <p className="text-[11.5px] font-semibold text-amber-700 mb-2">
            {t.mockup.missing_prefix} {t.mockup.missing_suffix}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {missing.map(kw => (
              <span key={kw}
                className="inline-flex items-center h-6 px-2.5 rounded-full text-[11.5px] font-medium border bg-amber-50 text-amber-700 border-amber-200">
                + {kw}
              </span>
            ))}
          </div>
        </div>
        {/* Present keywords */}
        <div>
          <p className="text-[11.5px] font-semibold text-emerald-700 mb-2">
            {t.mockup.present_prefix}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {present.map(kw => (
              <span key={kw}
                className="inline-flex items-center h-6 px-2.5 rounded-full text-[11.5px] font-medium border bg-emerald-50 text-emerald-700 border-emerald-200">
                ✓ {kw}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── BeforeAfterMockup: miniature ApplierPreview split-pane modal
// Left pane: job info card + score badge + missing keywords + CV Copilot input
// Right pane: structured document lines representing the generated PDF
function BeforeAfterMockup() {
  const { t } = useI18n()
  const missing = ['A/B Testing', 'SQL', 'Figma']
  return (
    <div
      className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex"
      style={{
        boxShadow: '0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)',
        height: 340,
      }}
    >
      {/* ── Left pane (38%) — mirrors ApplierPreview left panel ── */}
      <div
        className="flex flex-col shrink-0 border-r border-slate-200 overflow-hidden"
        style={{ width: '40%', padding: '16px 14px 16px 16px' }}
      >
        {/* Title */}
        <p className="text-[13px] font-semibold text-slate-900 tracking-tight leading-snug">
          {t.mockup.tailored_title}
        </p>
        <p className="text-[11px] text-slate-500 mt-0.5 mb-3">
          {t.mockup.ai_written_sub}
        </p>

        {/* JobInfoCard replica — rounded-xl border border-slate-200 */}
        <div
          className="rounded-xl border border-slate-200 bg-white p-3 mb-3 flex items-start gap-2.5"
          style={{ boxShadow: '0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04)' }}
        >
          {/* Company initial avatar */}
          <div
            className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-[13px] font-bold bg-ja-primarySubtle text-ja-primary"
          >
            W
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-semibold text-slate-900 leading-snug truncate">
              Senior Product Manager
            </p>
            <p className="text-[11px] text-slate-500 mt-0.5 truncate">
              <span className="font-medium text-slate-700">Wix</span>
              <span className="mx-1 text-slate-300">·</span>
              Tel Aviv
            </p>
            <span
              className="inline-block mt-1.5 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-ja-primarySubtle text-ja-primary"
            >
              88% match
            </span>
          </div>
        </div>

        {/* Missing keywords section */}
        <div className="mb-3">
          <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400 mb-1.5">
            {t.mockup.missing_kw}
          </p>
          <div className="flex flex-wrap gap-1">
            {missing.map(kw => (
              <span key={kw}
                className="inline-flex items-center h-5 px-2 rounded-full text-[10.5px] font-medium border bg-amber-50 text-amber-700 border-amber-200">
                + {kw}
              </span>
            ))}
          </div>
        </div>

        {/* CV Copilot box — exact inline style from ApplierPreview */}
        <div
          className="mt-auto"
          style={{
            borderRadius: 8,
            border: '1px solid var(--ja-line)',
            background: 'white',
            padding: '9px 10px 10px',
          }}
        >
          <p className="text-ja-primary" style={{ fontSize: 10, fontWeight: 700, marginBottom: 5, letterSpacing: '0.4px', textTransform: 'uppercase' }}>
            {t.mockup.cv_copilot}
          </p>
          <div
            style={{
              width: '100%', borderRadius: 6, height: 44,
              background: 'var(--ja-bg)', border: '1px solid var(--ja-line)',
            }}
          />
          <div
            className="bg-ja-primary"
            style={{ marginTop: 6, width: '100%', height: 26, borderRadius: 20, opacity: 0.9 }}
          />
        </div>
      </div>

      {/* ── Right pane — document preview (PDF render area) ── */}
      <div className="flex-1 flex flex-col bg-slate-50 p-4 overflow-hidden">
        {/* Template selector buttons at top */}
        <div className="flex items-center gap-1.5 mb-3">
          {['Classic', 'Modern', 'Compact'].map((t, i) => (
            <button
              key={t}
              tabIndex={-1}
              className={`h-6 px-2.5 rounded-md text-[10.5px] font-medium border transition-colors ${
                i === 0
                  ? 'bg-white border-slate-300 text-slate-700'
                  : 'bg-transparent border-slate-200 text-slate-400'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Document body — structured content lines */}
        <div
          className="flex-1 rounded-xl bg-white border border-slate-200 p-4 flex flex-col gap-3 overflow-hidden"
          style={{ boxShadow: '0 1px 3px rgba(15,23,42,0.06)' }}
        >
          {/* Name / header block */}
          <div className="space-y-1.5">
            <div className="h-3 w-32 rounded bg-slate-900" />
            <div className="h-2 w-48 rounded bg-slate-300" />
          </div>
          <div className="border-t border-slate-100" />
          {/* Section label */}
          <div className="h-1.5 w-20 rounded bg-slate-400" />
          {/* Content lines */}
          <div className="space-y-1.5">
            <div className="h-2 w-full rounded bg-slate-200" />
            <div className="h-2 w-5/6 rounded bg-slate-200" />
            <div className="h-2 w-full rounded bg-slate-200" />
            <div className="h-2 w-4/5 rounded bg-slate-200" />
          </div>
          <div className="border-t border-slate-100" />
          {/* Second section */}
          <div className="h-1.5 w-24 rounded bg-slate-400" />
          <div className="space-y-1.5">
            <div className="h-2 w-full rounded bg-slate-200" />
            <div className="h-2 w-3/4 rounded bg-slate-200" />
            {/* Highlighted "added" keywords */}
            <div className="flex gap-1.5 pt-0.5">
              <div className="h-2 w-14 rounded bg-emerald-100" />
              <div className="h-2 w-10 rounded bg-emerald-100" />
              <div className="h-2 w-12 rounded bg-emerald-100" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function LandingPage() {
  const router = useRouter()
  const { t, dir } = useI18n()
  const l = t.landing

  // Fade-in-up animation on scroll — adds .ja-visible when section enters viewport
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>('.ja-animate-section')
    if (!els.length) return
    const io = new IntersectionObserver(
      entries => {
        entries.forEach(e => {
          if (e.isIntersecting) {
            const el = e.target as HTMLElement
            el.style.animationDelay = el.dataset.delay ?? '0ms'
            el.classList.add('ja-visible')
            io.unobserve(el)
          }
        })
      },
      { threshold: 0.12 },
    )
    els.forEach(el => io.observe(el))
    return () => io.disconnect()
  }, [])

  const bentoIcons = [
    <svg key="privacy" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    </svg>,
    <svg key="fast" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
    </svg>,
    <svg key="multiplatform" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
    </svg>,
    <svg key="coverletter" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>,
    <svg key="tracker" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
    </svg>,
    <svg key="profile" width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
    </svg>,
  ]

  function BulletList({ bullets }: { bullets: readonly string[] }) {
    return (
      <ul className="mt-6 space-y-3">
        {bullets.map(item => (
          <li key={item} className="flex items-center gap-2.5 text-[13px] text-slate-700">
            <span className="w-4 h-4 rounded-full bg-ja-primarySubtle text-ja-primary flex items-center justify-center flex-shrink-0">
              <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </span>
            {item}
          </li>
        ))}
      </ul>
    )
  }

  const arrowStyle = { transform: dir === 'rtl' ? 'rotate(180deg)' : 'none' }

  // SVG grid pattern — faint slate-200 lines, tiled as a bg-image
  const gridBg = `url("data:image/svg+xml,%3Csvg width='40' height='40' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M 40 0 L 0 0 0 40' fill='none' stroke='%23CBD5E1' stroke-width='0.5' opacity='0.55'/%3E%3C/svg%3E")`

  return (
    <div className="min-h-screen overflow-x-hidden bg-ja-bg">

      {/* ── Ambient background layer (grid + gradient orbs) ──────────────── */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 z-0"
        style={{ backgroundImage: gridBg, backgroundSize: '40px 40px' }}
      />
      {/* Soft teal orb — top-left */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed z-0"
        style={{
          top: '-160px', left: '-120px',
          width: 520, height: 520,
          background: 'radial-gradient(circle, rgba(13,148,136,0.08) 0%, transparent 70%)',
          borderRadius: '50%',
          filter: 'blur(32px)',
        }}
      />
      {/* Soft slate orb — bottom-right */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed z-0"
        style={{
          bottom: '-180px', right: '-100px',
          width: 600, height: 600,
          background: 'radial-gradient(circle, rgba(100,116,139,0.07) 0%, transparent 70%)',
          borderRadius: '50%',
          filter: 'blur(40px)',
        }}
      />

      {/* All page content sits above the ambient layer */}
      <div className="relative z-10">

      {/* ── Sticky header ─────────────────────────────────────────────────── */}
      <header className="w-full bg-white/90 backdrop-blur border-b border-slate-100 sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-6 sm:px-12 h-[60px] flex items-center justify-between">
          <span className="text-xl font-bold tracking-tight text-slate-900">JobApply</span>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <button
              onClick={() => router.push('/login')}
              className="h-9 px-4 rounded-lg text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 border border-slate-200 transition-colors"
            >
              {l.nav.sign_in}
            </button>
            <button
              onClick={() => router.push('/login')}
              className="h-9 px-5 rounded-lg text-sm font-semibold text-white bg-ja-primary hover:bg-ja-primaryHover transition-colors"
            >
              {l.nav.get_started}
            </button>
          </div>
        </div>
      </header>

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <section className="py-24 px-6 sm:px-12 text-center bg-white">
        <span className="inline-block text-[10.5px] font-bold tracking-widest uppercase text-teal-600 bg-teal-50 px-3 py-1 rounded mb-6">
          {l.hero.eyebrow}
        </span>
        <h1 className="text-4xl sm:text-[52px] font-bold text-slate-900 tracking-tight leading-tight mb-6 max-w-3xl mx-auto">
          {l.hero.h1_line1}<br />
          <span className="text-ja-primary">{l.hero.h1_line2}</span>
        </h1>
        <p className="text-lg text-slate-500 max-w-2xl mx-auto mb-10 leading-relaxed">
          {l.hero.sub}
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <button
            onClick={() => router.push('/login')}
            className="inline-flex items-center gap-2 h-12 px-8 rounded-lg text-sm font-semibold text-white shadow-sm bg-ja-primary hover:bg-ja-primaryHover transition-colors"
          >
            {l.hero.cta_primary}
            <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
              style={arrowStyle}>
              <line x1="5" y1="12" x2="19" y2="12" />
              <polyline points="12 19 19 12 12 5" />
            </svg>
          </button>
          <button
            onClick={() => {
              document.getElementById('how-it-works')?.scrollIntoView({ behavior: 'smooth' })
            }}
            className="inline-flex items-center gap-2 h-12 px-6 rounded-lg text-sm font-medium text-slate-600 border border-slate-200 hover:bg-slate-50 transition-colors"
          >
            {l.hero.cta_secondary}
          </button>
        </div>
        <p className="mt-4 text-xs text-slate-400">{l.hero.no_credit_card}</p>

        {/* Hero UI Mockup */}
        <ATSMockup />
      </section>

      {/* ── Social proof band ─────────────────────────────────────────────── */}
      <section className="bg-slate-50 border-y border-slate-100 py-10 px-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-center text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-8">
            {l.social_proof.heading}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
            {l.social_proof.stats.map(stat => (
              <div key={stat.label}>
                <p className="text-2xl font-bold text-slate-900 tracking-tight">{stat.num}</p>
                <p className="text-[12px] text-slate-500 mt-1">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Feature deep-dives (Z-pattern) ────────────────────────────────── */}
      <div id="how-it-works">

        {/* Section A — Scan: text left, visual right */}
        <section className="py-24 bg-white border-b border-slate-100">
          <div className="max-w-6xl mx-auto px-6 sm:px-12">
            <div className="ja-animate-section grid grid-cols-1 md:grid-cols-2 gap-16 items-center" data-delay="0ms">
              {/* Text */}
              <div>
                <span className="text-[10.5px] font-bold tracking-widest uppercase text-teal-600">{l.section_a.step}</span>
                <h2 className="mt-3 text-3xl font-bold text-slate-900 tracking-tight leading-snug">
                  {l.section_a.h2_l1}<br />{l.section_a.h2_l2}
                </h2>
                <p className="mt-4 text-base text-slate-500 leading-relaxed max-w-md">
                  {l.section_a.body}
                </p>
                <BulletList bullets={l.section_a.bullets} />
              </div>
              {/* Visual */}
              <div>
                <FeedMockup />
              </div>
            </div>
          </div>
        </section>

        {/* Section B — Analysis: visual left, text right */}
        <section className="py-24 bg-slate-50 border-b border-slate-100">
          <div className="max-w-6xl mx-auto px-6 sm:px-12">
            <div className="ja-animate-section grid grid-cols-1 md:grid-cols-2 gap-16 items-center" data-delay="60ms">
              {/* Visual */}
              <div>
                <KeywordChipsMockup />
              </div>
              {/* Text */}
              <div>
                <span className="text-[10.5px] font-bold tracking-widest uppercase text-teal-600">{l.section_b.step}</span>
                <h2 className="mt-3 text-3xl font-bold text-slate-900 tracking-tight leading-snug">
                  {l.section_b.h2_l1}<br />{l.section_b.h2_l2}
                </h2>
                <p className="mt-4 text-base text-slate-500 leading-relaxed max-w-md">
                  {l.section_b.body}
                </p>
                <BulletList bullets={l.section_b.bullets} />
              </div>
            </div>
          </div>
        </section>

        {/* Section C — Tailor: text left, visual right */}
        <section className="py-24 bg-white border-b border-slate-100">
          <div className="max-w-6xl mx-auto px-6 sm:px-12">
            <div className="ja-animate-section grid grid-cols-1 md:grid-cols-2 gap-16 items-center" data-delay="60ms">
              {/* Text */}
              <div>
                <span className="text-[10.5px] font-bold tracking-widest uppercase text-teal-600">{l.section_c.step}</span>
                <h2 className="mt-3 text-3xl font-bold text-slate-900 tracking-tight leading-snug">
                  {l.section_c.h2_l1}<br />{l.section_c.h2_l2}
                </h2>
                <p className="mt-4 text-base text-slate-500 leading-relaxed max-w-md">
                  {l.section_c.body}
                </p>
                <BulletList bullets={l.section_c.bullets} />
              </div>
              {/* Visual */}
              <div>
                <BeforeAfterMockup />
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* ── Bento box grid — secondary features ───────────────────────────── */}
      <section className="py-24 bg-slate-50 border-b border-slate-100">
        <div className="max-w-6xl mx-auto px-6 sm:px-12">
          <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 text-center mb-4">
            {l.bento.eyebrow}
          </p>
          <h2 className="text-3xl font-bold text-slate-900 tracking-tight text-center mb-12">
            {l.bento.h2_l1}<br />{l.bento.h2_l2}
          </h2>
          <div className="ja-animate-section grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5" data-delay="0ms">
            {l.bento.cards.map((card, i) => (
              <div
                key={card.title}
                className="bg-white rounded-2xl border border-slate-100 p-6"
                style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.02), 0 20px 40px rgba(0,0,0,0.03)' }}
              >
                <div className="w-9 h-9 rounded-xl flex items-center justify-center mb-4 bg-ja-primarySubtle text-ja-primary">
                  {bentoIcons[i]}
                </div>
                <h3 className="text-[15px] font-bold text-slate-900 tracking-tight mb-2">{card.title}</h3>
                <p className="text-[13px] text-slate-500 leading-relaxed">{card.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ─────────────────────────────────────────────────────── */}
      <section className="py-24 px-6 text-center bg-ja-primary">
        <h2 className="text-3xl sm:text-4xl font-bold text-white tracking-tight mb-4">
          {l.cta_final.h2}
        </h2>
        <p className="text-base text-teal-100 mb-10 max-w-lg mx-auto leading-relaxed">
          {l.cta_final.body}
        </p>
        <button
          onClick={() => router.push('/login')}
          className="inline-flex items-center gap-2 h-12 px-10 rounded-lg text-sm font-semibold text-teal-700 bg-white shadow-sm transition-opacity hover:opacity-90"
        >
          {l.cta_final.button}
          <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
            style={arrowStyle}>
            <line x1="5" y1="12" x2="19" y2="12" />
            <polyline points="12 19 19 12 12 5" />
          </svg>
        </button>
      </section>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <footer className="bg-slate-900 py-14 px-6 sm:px-12 relative z-10">
        <div className="max-w-6xl mx-auto">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-8 mb-10">
            {l.footer.cols.map(col => (
              <div key={col.heading}>
                <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-4">{col.heading}</p>
                <ul className="space-y-2.5">
                  {col.links.map(link => (
                    <li key={link}>
                      <span className="text-[13px] text-slate-500 hover:text-slate-300 cursor-pointer transition-colors">{link}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="border-t border-slate-800 pt-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <span className="text-lg font-bold tracking-tight text-white">JobApply</span>
            <p className="text-[12px] text-slate-500">
              &copy; {new Date().getFullYear()} JobApply. {l.footer.copyright}
            </p>
          </div>
        </div>
      </footer>

      </div>{/* /relative z-10 */}
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────

export default function HomePage() {
  const { user, loading } = useAuth()

  // Auth resolving — neutral spinner, no flash of either surface
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="w-8 h-8 rounded-full border-2 border-slate-200 border-t-teal-500 animate-spin" />
      </div>
    )
  }

  // Unauthenticated → show the public landing page
  if (!user) return <LandingPage />

  // Authenticated → existing migration gate + dashboard
  return (
    <MigrationGate>
      <HomePageContent />
    </MigrationGate>
  )
}
