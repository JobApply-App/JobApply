'use client'
import { useState, useEffect, useRef } from 'react'
import { TOKENS } from '@/lib/tokens'
import type { ApiAgentStatus, AgentState, AgentName, ApiFeedJob } from '@/lib/apiTypes'
import { startAnalysis, syncPipeline } from '@/lib/api'
import { StatusDot } from './ui/StatusDot'
import { Skeleton } from './ui/Skeleton'
import { ArrowIcon, SparkIcon } from './icons'
import { JobCard } from './JobCard'
import type { Tone } from '@/lib/tokens'

// ── Per-agent accent colours ──────────────────────────────────────────────────

const AGENT_ACCENT: Record<AgentName, string> = {
  'Scraper':             TOKENS.color.primary,
  'Sourcing Specialist': TOKENS.color.violet,
  'Content Strategist':  TOKENS.color.success,
  'Quality Guard':       TOKENS.color.warn,
}

// Status color semantics (matches UI/UX spec):
//   Gray    = Idle / Paused   → muted
//   Pulsing Blue = Processing (active or queued) → primary with pulse
//   Solid Green  = Completed  → success without pulse (pipeline-level indicator)
//   Red     = Error           → danger with pulse
const STATE_META: Record<AgentState, { tone: Tone; label: string; pulse: boolean }> = {
  active: { tone: 'primary', label: 'Processing', pulse: true  },
  idle:   { tone: 'muted',   label: 'Idle',       pulse: false },
  queued: { tone: 'primary', label: 'Queued',     pulse: true  },
  error:  { tone: 'danger',  label: 'Error',      pulse: true  },
  paused: { tone: 'muted',   label: 'Paused',     pulse: false },
}

// ── Single agent card (read-only) ─────────────────────────────────────────────
//
// Cards are purely observational — they reflect backend pipeline state via the
// 5-second polling loop. All execution is triggered by the single "Run Pipeline"
// button in the section header. No per-card action buttons or developer metrics.

function AgentCard({ agent }: { agent: ApiAgentStatus }) {
  const accent = AGENT_ACCENT[agent.name]
  const s      = STATE_META[agent.state]

  return (
    <div
      className="rounded-xl bg-white border border-slate-200 p-4 hover:shadow-sm transition-shadow"
      style={{ boxShadow: TOKENS.shadow.card }}
    >
      {/* Header: avatar + name + state badge */}
      <div className="flex items-center gap-2.5">
        <div
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-[18px] font-bold shrink-0"
          style={{ background: `${accent}14`, color: accent }}
        >
          {agent.name[0]}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[14px] font-semibold text-slate-900">
              {agent.name}
            </span>
            <StatusDot tone={s.tone} pulse={s.pulse} size={5} />
            <span
              className="text-[10.5px] font-medium px-1.5 rounded"
              style={{
                background: s.tone === 'muted'   ? '#F1F5F9' :
                            s.tone === 'primary' ? 'oklch(0.95 0.03 255)' :
                            s.tone === 'danger'  ? 'oklch(0.97 0.03 25)' : '#F1F5F9',
                color:      s.tone === 'muted'   ? '#94A3B8' :
                            s.tone === 'primary' ? TOKENS.color.primary :
                            s.tone === 'danger'  ? TOKENS.color.danger : '#94A3B8',
              }}
            >
              {s.label}
            </span>
          </div>
          <div className="text-[12px] text-slate-500 mt-0.5">{agent.role}</div>
        </div>
      </div>

      {/* Live status message — text wraps freely, never truncated */}
      <div className="mt-3 text-[12px] leading-relaxed min-h-[2.5rem]">
        {agent.state === 'active' && agent.current_task && (
          <span className="text-slate-700">
            <span
              className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle animate-pulse"
              style={{ background: accent }}
            />
            {agent.current_task}
          </span>
        )}
        {agent.state === 'active' && !agent.current_task && (
          <span className="text-slate-500">Running…</span>
        )}
        {agent.state === 'idle'   && <span className="text-slate-400">Idle. Waiting for the next pipeline run.</span>}
        {agent.state === 'queued' && (
          <span className="text-slate-600">
            {agent.queue_msg || 'Queued. Starting shortly…'}
          </span>
        )}
        {agent.state === 'error'  && <span className="text-rose-600">{agent.error_msg}</span>}
        {agent.state === 'paused' && <span className="text-slate-400">Paused.</span>}
      </div>
    </div>
  )
}

// ── Skeleton card ─────────────────────────────────────────────────────────────

function AgentCardSkeleton() {
  return (
    <div
      className="rounded-xl bg-white border border-slate-200 p-4"
      style={{ boxShadow: TOKENS.shadow.card }}
    >
      <div className="flex items-center gap-2.5">
        <Skeleton className="h-9 w-9 rounded-lg shrink-0" />
        <div className="space-y-1.5 flex-1 min-w-0">
          <Skeleton className="h-3.5 w-20" />
          <Skeleton className="h-3 w-28" />
        </div>
      </div>
      <Skeleton className="h-3 w-full mt-4" />
      <Skeleton className="h-3 w-4/5 mt-1.5" />
    </div>
  )
}

// ── Pipeline flow bar ─────────────────────────────────────────────────────────

function AgentPipeline({ agents }: { agents: ApiAgentStatus[] }) {
  return (
    <div className="flex items-center gap-1 text-[11px] text-slate-500 px-0.5 pt-1 flex-wrap">
      {agents.map((a, i) => (
        <span key={a.id} className="inline-flex items-center gap-1">
          <span className="flex items-center gap-1">
            <StatusDot
              tone={
                a.state === 'active' ? 'success' :
                a.state === 'error'  ? 'danger'  :
                a.state === 'queued' ? 'warn'    : 'muted'
              }
              pulse={a.state === 'active' || a.state === 'error'}
              size={6}
            />
            <span className="font-medium text-slate-600">{a.name}</span>
          </span>
          {i < agents.length - 1 && <span className="text-slate-300 mx-1">→</span>}
        </span>
      ))}
    </div>
  )
}

// ── Error banner ──────────────────────────────────────────────────────────────

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 flex items-center justify-between gap-4">
      <p className="text-[13px] text-rose-700">
        <span className="font-medium">Agent status unavailable.</span>
        <span className="text-rose-500"> {message}</span>
      </p>
      <button
        onClick={onRetry}
        className="text-[12px] font-medium text-rose-700 underline underline-offset-2 hover:text-rose-900 shrink-0"
      >
        Retry
      </button>
    </div>
  )
}

// ── Analyze trigger panel ─────────────────────────────────────────────────────
// Zero-Click: startAnalysis() blocks until fully processed and returns the
// complete JobMatch directly — no polling, no setInterval.

type TriggerState = 'idle' | 'loading' | 'success' | 'error'

function AnalyzeTrigger({
  onJobAnalyzed,
  onTailorCV,
}: {
  onJobAnalyzed?: (job: ApiFeedJob) => void
  onTailorCV?:    (job: ApiFeedJob) => void
}) {
  const [url,         setUrl]         = useState('')
  const [status,      setStatus]      = useState<TriggerState>('idle')
  const [message,     setMessage]     = useState('')
  const [analyzedJob, setAnalyzedJob] = useState<ApiFeedJob | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return

    setStatus('loading')
    setMessage('')
    setAnalyzedJob(null)

    try {
      // Blocking call — returns the complete JobMatch when done, or throws on failure.
      const res = await startAnalysis(url.trim())
      setStatus('success')
      setMessage(`"${res.title}" added. ATS score ${res.match_score.toFixed(1)}.`)
      setAnalyzedJob(res)
      setUrl('')
      onJobAnalyzed?.(res)
    } catch (err) {
      setStatus('error')
      setMessage(err instanceof Error ? err.message : 'Analysis failed')
    }
  }

  const loading = status === 'loading'

  return (
    <div
      className="mt-8 rounded-2xl border border-slate-100 bg-white p-5"
      style={{ boxShadow: TOKENS.shadow.card }}
    >
      <div className="flex items-center gap-2.5 mb-4">
        <span
          className="inline-flex h-8 w-8 items-center justify-center rounded-xl shrink-0"
          style={{ background: TOKENS.color.primarySoft, color: TOKENS.color.primary }}
        >
          <SparkIcon s={15} />
        </span>
        <div className="min-w-0">
          <span className="block text-[13.5px] font-semibold text-slate-900 leading-tight">Analyze a job URL</span>
          <span className="block text-[12px] text-slate-400">Scrape · structure · score in one shot</span>
        </div>
      </div>

      {/* Command-palette input — leading glyph, inset field, docked Run button */}
      <form
        onSubmit={handleSubmit}
        className="group flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/60 p-1.5 pl-3.5 transition-all duration-200 focus-within:bg-white focus-within:border-teal-300"
        style={{ boxShadow: 'inset 0 1px 2px rgba(15,23,42,0.05)' }}
      >
        <span className="shrink-0 text-slate-300 group-focus-within:text-teal-500 transition-colors" aria-hidden>
          <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
        </span>
        <input
          type="url"
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="Paste a job URL, e.g. https://jobs.lever.co/company/job-id"
          className="flex-1 h-9 bg-transparent text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none min-w-0"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !url.trim()}
          className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg text-[13px] font-semibold text-white transition-all duration-150 active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
          style={{ background: TOKENS.color.primary, boxShadow: '0 1px 3px rgba(13,148,136,0.35)' }}
        >
          {loading ? (
            <>
              <span
                className="inline-block h-3 w-3 rounded-full border-[1.5px] animate-spin"
                style={{ borderColor: 'rgba(255,255,255,.4)', borderTopColor: '#fff' }}
              />
              Analysing…
            </>
          ) : (
            <><ArrowIcon s={13} /> Run</>
          )}
        </button>
      </form>
      {message && (
        <p className={`mt-2.5 text-[12px] font-medium ${status === 'error' ? 'text-rose-600' : 'text-emerald-600'}`}>
          {message}
        </p>
      )}

      {/* Result job card — rendered immediately from the API response, no polling */}
      {analyzedJob && (
        <div className="mt-4">
          <p className="text-[11.5px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
            ✦ Analysis Result
          </p>
          <JobCard
            job={analyzedJob}
            isTopFit={analyzedJob.match_score > 60}
            onSkip={() => setAnalyzedJob(null)}
            onSave={() => {}}
            onTailorCV={onTailorCV ? () => onTailorCV(analyzedJob) : () => {}}
          />
        </div>
      )}
    </div>
  )
}

// ── Public component ──────────────────────────────────────────────────────────

interface AgentStatusCenterProps {
  agents:        ApiAgentStatus[]
  loading:       boolean
  error:         string | null
  onRetry:       () => void
  onJobAnalyzed?: (job: ApiFeedJob) => void
  onTailorCV?:   (job: ApiFeedJob) => void
}

export function AgentStatusCenter({ agents, loading, error, onRetry, onJobAnalyzed, onTailorCV }: AgentStatusCenterProps) {
  const [syncing,        setSyncing]        = useState(false)
  const [syncErr,        setSyncErr]        = useState<string | null>(null)
  const [pipelineDone,   setPipelineDone]   = useState(false)
  const [pipelineFailed, setPipelineFailed] = useState(false)

  // Tracks whether the pipeline has been seen as active since the last sync
  // click.  Used to detect the active → idle transition so we can:
  //   (a) clear `syncing` immediately (fixes button staying stuck)
  //   (b) surface the correct outcome toast — success green or failure red
  const pipelineWasActiveRef = useRef(false)

  // Pipeline is live if any agent is actively working or queued.
  // The master button stays disabled during live execution — the cards show
  // real-time progress via the 5 s poll loop.
  const isPipelineRunning = agents.some(
    a => a.state === 'active' || a.state === 'queued'
  )

  // ── Button stickiness + error cascade fix ────────────────────────────────────
  // Problem: clicking "Run Pipeline" sets syncing=true with a 6s timer guard.
  // If the pipeline completes (success OR error/timeout) faster than 6s,
  // isPipelineRunning goes false but syncing is still true, leaving the button
  // stuck and hiding the failure state from the user.
  //
  // Fix: watch the isPipelineRunning transition (active→idle or active→error).
  // The moment the pipeline confirms it's running (→ true), latch the ref.
  // When it returns to false (all agents idle/error), immediately:
  //   • Clear syncing — unblocks the button without waiting for the 6s timer
  //   • Detect error state — show failure banner instead of success toast
  //
  // agents is intentionally in the dep array so that if isPipelineRunning was
  // already false on the first render after error (same tick), the agents
  // state update also triggers re-evaluation.
  useEffect(() => {
    if (isPipelineRunning) {
      // Pipeline is running — mark as seen
      pipelineWasActiveRef.current = true
    } else if (pipelineWasActiveRef.current) {
      // Pipeline just finished (was active, now all agents idle/error)
      pipelineWasActiveRef.current = false
      setSyncing(false)           // always unblock the button immediately
      setPipelineDone(false)      // clear any stale success toast
      setPipelineFailed(false)    // clear any stale failure toast

      const hasError = agents.some(a => a.state === 'error')
      if (hasError) {
        setPipelineFailed(true)   // surfaces inline error banner
      } else {
        setPipelineDone(true)     // surfaces green completion toast
      }
    }
  }, [isPipelineRunning, agents])

  // Auto-dismiss completion toast after 5 s
  useEffect(() => {
    if (!pipelineDone) return
    const t = setTimeout(() => setPipelineDone(false), 5_000)
    return () => clearTimeout(t)
  }, [pipelineDone])

  // Auto-dismiss failure banner after 8 s (longer — user needs time to read error cards)
  useEffect(() => {
    if (!pipelineFailed) return
    const t = setTimeout(() => setPipelineFailed(false), 8_000)
    return () => clearTimeout(t)
  }, [pipelineFailed])

  const canSync = !isPipelineRunning && !syncing && agents.length > 0 && !loading

  const handleSync = async () => {
    if (!canSync) return
    setSyncing(true)
    setSyncErr(null)
    setPipelineDone(false)
    setPipelineFailed(false)
    try {
      const res = await syncPipeline()
      if (res.triggered) {
        // Stay in "syncing" state until the first poll tick confirms queued/active.
        // 6 s > 5 s poll interval guarantees at least one cycle before the button
        // re-enables — pipelineWasActiveRef effect will short-circuit this timer
        // once it detects the active→idle transition.
        setTimeout(() => setSyncing(false), 6_000)
      } else {
        // Backend said pipeline is already running — reset immediately so we
        // don't show a false "Syncing…" state.
        setSyncing(false)
      }
    } catch (err) {
      setSyncErr(err instanceof Error ? err.message : 'Failed to start pipeline')
      setSyncing(false)
    }
  }

  const buttonBusy = syncing || isPipelineRunning

  return (
    <section>
      {/* ── Live Pipeline banner — premium dark-teal SaaS surface ── */}
      <div
        className="relative overflow-hidden rounded-2xl border border-white/10 p-6 mb-5"
        style={{
          background: 'linear-gradient(135deg, #08201E 0%, #0C302B 55%, #0F3B35 100%)',
          boxShadow: '0 12px 32px rgba(8,32,30,0.30), inset 0 1px 0 rgba(255,255,255,0.06)',
        }}
      >
        {/* Rich teal glow, top-right */}
        <div
          aria-hidden
          className="pointer-events-none absolute -right-20 -top-24 h-56 w-56 rounded-full blur-3xl"
          style={{ background: 'radial-gradient(circle, rgba(13,148,136,0.45) 0%, transparent 70%)' }}
        />
        {/* Soft emerald counter-glow, bottom-left */}
        <div
          aria-hidden
          className="pointer-events-none absolute -left-24 -bottom-24 h-56 w-56 rounded-full blur-3xl"
          style={{ background: 'radial-gradient(circle, rgba(5,150,105,0.22) 0%, transparent 70%)' }}
        />
        <div className="relative">
          <div className="flex items-center gap-2 mb-2.5">
            {/* Pulsing live dot */}
            <span className="relative inline-flex h-2 w-2 shrink-0">
              <span
                className="absolute inline-flex h-full w-full rounded-full opacity-70 animate-ping"
                style={{ background: '#2DD4BF' }}
              />
              <span
                className="relative inline-flex h-2 w-2 rounded-full"
                style={{ background: '#2DD4BF' }}
              />
            </span>
            <span
              className="text-[11px] uppercase tracking-[0.16em] font-semibold"
              style={{ color: '#99F6E4' }}
            >
              Live Pipeline Status
            </span>
          </div>
          <h3 className="text-[18px] font-semibold text-white tracking-tight leading-snug">
            Job Apply is searching while you focus on what matters.
          </h3>
          <p className="text-[13px] mt-1.5 max-w-[60ch] leading-relaxed" style={{ color: 'rgba(204,251,241,0.75)' }}>
            Four agents work quietly in the background. They scan, analyze, rank, and apply to roles that fit your profile.
          </p>
        </div>
      </div>

      {/* ── Section header: title + master Run Pipeline button ── */}
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold text-slate-900 tracking-tight">
            Agent Status
          </h2>
          <p className="text-[12.5px] text-slate-500 mt-0.5">
            Live state of the 4-stage analysis pipeline
          </p>
        </div>

        {/* Master pipeline trigger */}
        <button
          onClick={handleSync}
          disabled={!canSync}
          className="shrink-0 inline-flex items-center gap-2 h-8 px-4 rounded-lg text-[12.5px] font-semibold transition-all duration-150 active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed mt-0.5"
          style={canSync
            ? { background: TOKENS.color.primary, color: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,.15)' }
            : { background: TOKENS.color.line, color: TOKENS.color.muted }
          }
        >
          {buttonBusy ? (
            <>
              <span
                className="inline-block h-3 w-3 rounded-full border-[1.5px] animate-spin shrink-0"
                style={{ borderColor: 'rgba(255,255,255,.35)', borderTopColor: '#fff' }}
              />
              Running…
            </>
          ) : (
            <>
              <ArrowIcon s={12} />
              Run Pipeline
            </>
          )}
        </button>
      </div>

      {/* Sync error feedback */}
      {syncErr && (
        <p className="mb-2 text-[12px] text-rose-600">{syncErr}</p>
      )}

      {/* Pipeline completion toast — green, auto-dismisses after 5 s */}
      {pipelineDone && (
        <div className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="shrink-0">
              <circle cx="8" cy="8" r="7" fill="#10B981" fillOpacity="0.15" stroke="#10B981" strokeWidth="1.5" />
              <path d="M5 8l2 2 4-4" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <p className="text-[13px] text-emerald-800">
              <span className="font-semibold">Pipeline complete.</span>
              <span className="text-emerald-600"> Job feed refreshed with the latest matches.</span>
            </p>
          </div>
          <button
            onClick={() => setPipelineDone(false)}
            className="text-emerald-500 hover:text-emerald-700 shrink-0 transition-colors"
            aria-label="Dismiss"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      )}

      {/* Pipeline failure banner — red, auto-dismisses after 8 s */}
      {/* Complements the per-card error_msg already shown on each agent card */}
      {pipelineFailed && (
        <div className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="shrink-0">
              <circle cx="8" cy="8" r="7" fill="#EF4444" fillOpacity="0.12" stroke="#EF4444" strokeWidth="1.5" />
              <path d="M8 5v3M8 10.5v.5" stroke="#EF4444" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <p className="text-[13px] text-rose-800">
              <span className="font-semibold">Pipeline stopped.</span>
              <span className="text-rose-600"> One or more agents hit an error. Check the cards below for details.</span>
            </p>
          </div>
          <button
            onClick={() => setPipelineFailed(false)}
            className="text-rose-400 hover:text-rose-600 shrink-0 transition-colors"
            aria-label="Dismiss"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      )}

      {/* Error banner */}
      {error && <ErrorBanner message={error} onRetry={onRetry} />}

      {/* Agent grid — cards are read-only status monitors */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => <AgentCardSkeleton key={i} />)
          : agents.map(a => <AgentCard key={a.id} agent={a} />)
        }
      </div>

      {/* Pipeline flow */}
      {!loading && agents.length > 0 && <AgentPipeline agents={agents} />}

      {/* Workflow trigger */}
      <AnalyzeTrigger onJobAnalyzed={onJobAnalyzed} onTailorCV={onTailorCV} />
    </section>
  )
}
