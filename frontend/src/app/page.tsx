'use client'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useI18n } from '@/contexts/I18nContext'
import { DEFAULT_SETTINGS, type AutomationSettings } from '@/lib/data'
import { useJobMatches }        from '@/hooks/useJobMatches'
import { Header }               from '@/components/Header'
import type { Tab }             from '@/components/Header'
import { RequiredDetailsGate }  from '@/components/RequiredDetailsGate'
import { ControlsSheet }        from '@/components/ControlsSheet'
import { Overview }             from '@/components/Overview'
import { JobFeed }              from '@/components/JobFeed'
import { ApplicationsTab }      from '@/components/ApplicationsTab'
import { AllJobsTab }           from '@/components/AllJobsTab'
import { AnalyzeTrigger }       from '@/components/AgentStatusCenter'
import { ApplierPreview }       from '@/components/ApplierPreview'
import AuthGuard                from '@/components/AuthGuard'
import { AppSkeleton, hasStoredSession } from '@/components/AppSkeleton'
import { LandingPage }          from '@/components/landing/LandingPage'
import { useAuth }              from '@/contexts/AuthContext'
import { resolveDisplayName }   from '@/lib/nameUtils'
import type { Job }             from '@/lib/data'
import type { ApiFeedJob }      from '@/lib/apiTypes'

// ── Identity-sync gate ────────────────────────────────────────────────────────
//
// PURPOSE
//   On first login, sync the Supabase identity with the backend (account
//   linking by verified email, profile_completed backfill) before the
//   dashboard's data hooks mount.
//
// DESIGN — background sync, never a wait
//   The dashboard renders at once and sync-user runs beside it. It used to be
//   a blocking gate: a dark "Securing your workspace and activating agents…
//   Please wait." screen after every login (signOut clears localStorage, so
//   the cached flag below never survived a sign-in), waiting on a request to
//   a backend that can be slow. Ron, 2026-10-31: no waiting screen at all.
//   The case the gate protected is rare: this login re-linked rows from an
//   older account (Google after email sign-up). Only then is anything already
//   read stale, and the page reloads once so it reads the linked data.
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

function MigrationGate({ children }: { children: React.ReactNode }) {
  const { user, session, updateUserMeta } = useAuth()
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
      return
    }

    // ── First sync in this browser: runs beside the dashboard ─────────────────
    firedRef.current = true

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
          localStorage.setItem(storageKey, '1')
          window.location.reload()
          return
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
      .then(() => { localStorage.setItem(storageKey, '1') })
    // `updateUserMeta` is safe to depend on: AuthContext defines it as
    // useCallback(..., []), so its identity is fixed for the provider's
    // lifetime and listing it cannot make this effect run any more often.
  }, [user, session, updateUserMeta])

  return <>{children}</>
}

// ── Preferences & navigation helpers ─────────────────────────────────────────

const VALID_TABS: Tab[] = ['overview', 'feed', 'apps', 'all-jobs']
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
  const { t } = useI18n()
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
  const { jobs: rawJobs, feedJobs, loading: jobsLoading, error: jobsError } = useJobMatches()

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
        fitBrief:     f.fit_brief ?? null,
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
      fitBrief:     feedJob.fit_brief ?? null,
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

      <main className="flex-grow max-w-content mx-auto w-full px-4 sm:px-6 py-6 sm:py-8">
        {/* Overview/JobFeed render their own visible <h1> internally; ApplicationsTab
            and AllJobsTab don't, so this covers those two tabs without duplicating
            a heading on the tabs that already have one. */}
        {tab === 'apps' && <h1 className="sr-only">{t.header.nav.apps}</h1>}
        {tab === 'all-jobs' && <h1 className="sr-only">{t.header.nav.all_jobs}</h1>}

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
            {/* The four agent status cards and "Run Pipeline" are gone: their
                descriptions were written for a single user ("Why Ron?",
                "USER_PROFILE") and were shown to every user, the manual run
                timed out against slow job boards and spent AI budget, and the
                background search runs on its own regardless. What remains is
                the one useful piece — analyzing a pasted job link. */}
            <AnalyzeTrigger
              onJobAnalyzed={handleJobAnalyzed}
              onTailorCV={handleTailorCVFromOverview}
            />
          </div>
        )}

        {tab === 'feed' && (
          <JobFeed
            key={feedKey}
            preferences={settings}
            expandJobId={expandJobId}
            userId={user?.id ?? ''}
            initialFeedJobs={feedJobs}
            initialFeedJobsLoading={jobsLoading}
            initialFeedJobsFailed={jobsError !== null}
          />
        )}

        {tab === 'apps'  && <ApplicationsTab />}

        {tab === 'all-jobs' && <AllJobsTab />}
      </main>

      <RequiredDetailsGate />

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

// ── Page root ─────────────────────────────────────────────────────────────────

export default function HomePage() {
  const { user, loading } = useAuth()

  // Auth resolving (a local read, ~100ms): the app's frame if this browser
  // holds a session, otherwise the plain page colour — never a spinner.
  if (loading) {
    return hasStoredSession() ? <AppSkeleton /> : <div className="min-h-screen bg-ja-bg" />
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
