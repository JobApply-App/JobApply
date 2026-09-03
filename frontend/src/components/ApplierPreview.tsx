'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { LOCALES, type Locale } from '@/locales'
import { TOKENS } from '@/lib/tokens'
import { getScoreBand } from '@/lib/scoreBand'
import type { Job } from '@/lib/data'
import type { ApiFeedJob, CopilotResponse, MatchScoreResult, TemplateInfo } from '@/lib/apiTypes'
import type { ParsedCV } from '@/lib/cv'
import { parseCv, toLiveEditorCvData, resetToOriginal } from '@/lib/cvParser'
import { applyCvPatch, jsonEqual } from '@/lib/cvPatch'
import { fetchTemplates, renderPdf, downloadCvPdf, fetchMatchScore, fetchCachedCV, markJobApplied, ensureFreshToken, getAuthHeaders, saveCv } from '@/lib/api'
import { MatchScorePanel } from './MatchScorePanel'
import { TemplateSelectorBar } from './TemplateSelectorBar'
import { LiveEditor } from './LiveEditor'
import type { CvData } from './LiveEditor'

// ── Icons ─────────────────────────────────────────────────────────────────────

function Spinner({ size = 20 }: { size?: number }) {
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

function CheckIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function XIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

function RefreshIcon({ s = 15 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  )
}

function WandIcon({ s = 15 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 4V2" /><path d="M15 16v-2" /><path d="M8 9h2" />
      <path d="M20 9h2" /><path d="M17.8 11.8 19 13" /><path d="M15 9h0" />
      <path d="M17.8 6.2 19 5" /><path d="m3 21 9-9" /><path d="M12.2 6.2 11 5" />
    </svg>
  )
}

function InfoIcon({ s = 15 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  )
}

// ── Types ─────────────────────────────────────────────────────────────────────

type Phase =
  | 'idle'          // nothing generated yet
  | 'generating'    // TailorAgent running
  | 'missing_data'  // agent needs user input before it can proceed
  | 'preview'       // PDF ready, awaiting decision
  | 'revising'      // Gatekeeper running
  | 'applying'      // submitting application

interface CvState {
  cvData: Record<string, unknown>
  pdfB64: string
}

interface MissingDataRequest {
  id:       string
  question: string
  context?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function pdfDataUrl(b64: string) {
  // #toolbar=0&navpanes=0&scrollbar=0 suppresses Chrome/Firefox's native PDF
  // viewer chrome (the dark toolbar with zoom/print/download controls) so
  // the preview reads as an embedded CV, not an obviously-a-PDF-file frame.
  return `data:application/pdf;base64,${b64}#toolbar=0&navpanes=0&scrollbar=0`
}

// ── JobInfoCard ───────────────────────────────────────────────────────────────

function JobInfoCard({ job }: { job: Job }) {
  const A = useI18n().t.applier
  const band = getScoreBand(job.score)
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 mb-5"
      style={{ boxShadow: TOKENS.shadow.card }}>
      <div className="flex items-start gap-3">
        <div className="shrink-0 w-10 h-10 rounded-lg flex items-center justify-center text-[17px] font-bold select-none"
          style={{ background: TOKENS.color.primarySoft, color: TOKENS.color.primary }}>
          {job.company.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-[14.5px] font-semibold text-slate-900 leading-snug truncate">
            {job.title}
          </h3>
          <p className="text-[12.5px] text-slate-500 mt-0.5 truncate">
            <span className="font-medium text-slate-700">{job.company}</span>
            <span className="mx-1.5 text-slate-300">·</span>
            {job.location}
          </p>
          <div className="mt-2">
            <span className="inline-block text-[11px] font-semibold px-2 py-0.5 rounded-full tabular-nums"
              style={{ background: band.hexBg, color: band.hexFg }}>
              {A.pct_match.replace('{pct}', job.score.toFixed(1))}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── MissingDataForm — step-by-step wizard ────────────────────────────────────

function MissingDataForm({
  requests,
  answers,
  onChange,
  onSubmit,
  onSkip,
  submitting,
}: {
  requests:   MissingDataRequest[]
  answers:    Record<string, string>
  onChange:   (id: string, value: string) => void
  onSubmit:   () => void
  onSkip:     () => void
  submitting: boolean
}) {
  const A = useI18n().t.applier
  const [idx, setIdx] = useState(0)

  // Guard against stale index if requests array shrinks (shouldn't happen, but safe)
  const safeIdx   = Math.min(idx, requests.length - 1)
  const current   = requests[safeIdx]
  const isFirst   = safeIdx === 0
  const isLast    = safeIdx === requests.length - 1
  const total     = requests.length
  const curAnswer = (answers[current?.id ?? ''] || '').trim()
  const canNext   = curAnswer.length > 0

  if (!current) return null

  return (
    <div
      className="rounded-xl border border-slate-200 bg-white mb-4 flex flex-col"
      style={{ boxShadow: TOKENS.shadow.card, minHeight: 0 }}
    >
      {/* ── Header ── */}
      <div
        className="px-4 py-3 flex items-center justify-between border-b border-slate-100 shrink-0 rounded-t-xl"
        style={{ background: 'oklch(0.97 0.03 80)' }}
      >
        <div className="flex items-center gap-2">
          <span style={{ color: 'oklch(0.48 0.12 60)' }}><InfoIcon s={14} /></span>
          <p className="text-[12.5px] font-semibold" style={{ color: 'oklch(0.35 0.10 60)' }}>
            {A.additional_info}
          </p>
        </div>
        {total > 1 && (
          <span className="text-[11px] font-medium text-slate-400 shrink-0 ml-2">
            {safeIdx + 1} / {total}
          </span>
        )}
      </div>

      {/* ── Question body ── */}
      <div className="px-4 pt-4 pb-3 flex flex-col gap-2">
        <label className="text-[12.5px] font-medium text-slate-700 leading-snug">
          {current.question}
        </label>
        {current.context && (
          <p className="text-[11px] text-slate-400 leading-relaxed">{current.context}</p>
        )}
        <textarea
          key={current.id}
          value={answers[current.id] || ''}
          onChange={e => onChange(current.id, e.target.value)}
          placeholder={A.answer_placeholder}
          rows={3}
          disabled={submitting}
          className="w-full rounded-lg border border-slate-200 bg-slate-50 text-[12.5px] text-slate-800 placeholder-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-200 disabled:opacity-60 transition resize-none"
        />
      </div>

      {/* ── Progress dots ── */}
      {total > 1 && (
        <div className="flex justify-center gap-1.5 pb-1 shrink-0">
          {requests.map((_, i) => (
            <div
              key={i}
              className="w-1.5 h-1.5 rounded-full transition-colors duration-200"
              style={{ background: i === safeIdx ? TOKENS.color.primary : 'oklch(0.88 0 0)' }}
            />
          ))}
        </div>
      )}

      {/* ── Actions ── */}
      <div className="px-4 pb-4 pt-2 flex gap-2 shrink-0">
        {/* Back — visible from step 2 onwards */}
        {!isFirst && (
          <button
            onClick={() => setIdx(i => i - 1)}
            disabled={submitting}
            className="h-9 px-3 rounded-full text-[12px] text-slate-500 border border-slate-200 hover:bg-slate-50 transition disabled:opacity-50 shrink-0"
          >
            ← Back
          </button>
        )}

        {/* Next or Save & Continue */}
        {!isLast ? (
          <button
            onClick={() => setIdx(i => i + 1)}
            disabled={!canNext || submitting}
            className="flex-1 h-9 rounded-full text-[12.5px] font-semibold text-white flex items-center justify-center gap-1.5 transition disabled:opacity-50 active:scale-[0.98]"
            style={{ background: TOKENS.color.primary }}
          >
            Next →
          </button>
        ) : (
          <button
            onClick={onSubmit}
            disabled={!canNext || submitting}
            className="flex-1 h-9 rounded-full text-[12.5px] font-semibold text-white flex items-center justify-center gap-1.5 transition disabled:opacity-50 active:scale-[0.98]"
            style={{ background: TOKENS.color.primary }}
          >
            {submitting ? <><Spinner size={13} /> {A.generating}</> : A.save_continue}
          </button>
        )}

        {/* Skip — only on the first step so it doesn't appear mid-wizard */}
        {isFirst && (
          <button
            onClick={onSkip}
            disabled={submitting}
            className="h-9 px-3 rounded-full text-[12px] text-slate-500 border border-slate-200 hover:bg-slate-50 transition disabled:opacity-50 shrink-0"
            title={A.skip_all_title}
          >
            {A.skip_all}
          </button>
        )}
      </div>
    </div>
  )
}

// ── Banners ───────────────────────────────────────────────────────────────────

function GatekeeperBanner({ message }: { message: string }) {
  return (
    <div className="rounded-xl px-3.5 py-3 mb-4 text-[12px] leading-relaxed"
      style={{ background: 'oklch(0.97 0.03 80)', border: '1px solid oklch(0.90 0.06 80)', color: 'oklch(0.40 0.12 60)' }}>
      <span className="font-semibold">Not applied · </span>{message}
    </div>
  )
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-xl px-3.5 py-3 mb-4 text-[12px] leading-relaxed"
      style={{ background: 'oklch(0.97 0.02 25)', border: '1px solid oklch(0.91 0.04 25)', color: TOKENS.color.danger }}>
      {message}
    </div>
  )
}

function EmptyPreview() {
  const A = useI18n().t.applier
  const [before, after] = A.empty_body.split('{cta}')
  return (
    <div className="flex flex-col items-center gap-4 text-center px-10">
      <div className="w-16 h-16 rounded-2xl flex items-center justify-center"
        style={{ background: TOKENS.color.primarySoft }}>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
          stroke={TOKENS.color.primary} strokeWidth="1.5"
          strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
      </div>
      <div>
        <p className="text-[14px] font-semibold text-slate-700">{A.empty_title}</p>
        <p className="text-[12.5px] text-slate-400 mt-1 leading-relaxed">
          {before}<strong className="text-slate-600">{A.generate_cv}</strong>{after}
        </p>
      </div>
    </div>
  )
}

// ── ApplierPreview ────────────────────────────────────────────────────────────

// Progressive loading status messages. Module scope, not component scope: as a
// component-local literal this array was a fresh reference every render, so the
// rotation effect below could not list it as a dependency without restarting
// its interval on each render. Hoisting makes it a stable constant, which is
// what it always was semantically.

export interface ApplierPreviewProps {
  job:        Job
  /** Full API object — used for the readiness guard before calling the tailor endpoint. */
  feedJob:    ApiFeedJob
  onClose:    () => void
  onApplied?: (jobId: string) => void
}

export function ApplierPreview({ job, feedJob, onClose, onApplied }: ApplierPreviewProps) {
  const A = useI18n().t.applier
  const { locale } = useI18n()

  /**
   * Language the CV itself is written in, chosen per generation.
   *
   * Seeded from the interface language because that is the best available
   * guess, but deliberately not bound to it: the language someone reads the
   * app in and the language an employer reads their CV in are different
   * decisions, and an Israeli applying to a US company needs to make them
   * differently. Kept in local state rather than saved as a profile setting
   * so the choice is reconsidered per job instead of being decided once and
   * silently applied forever.
   */
  const [cvLang, setCvLang] = useState<Locale>(locale)
  // Follow the interface language until the user overrides it for this job.
  const cvLangTouched = useRef(false)
  useEffect(() => { if (!cvLangTouched.current) setCvLang(locale) }, [locale])
  const [phase,            setPhase]            = useState<Phase>('idle')
  const [cvState,          setCvState]          = useState<CvState | null>(null)
  const [gkMessage,        setGkMessage]        = useState('')
  const [error,            setError]            = useState('')
  // Missing-data state
  const [missingReqs,      setMissingReqs]      = useState<MissingDataRequest[]>([])
  const [answers,          setAnswers]          = useState<Record<string, string>>({})
  // B2C feature state
  const [matchScore,       setMatchScore]       = useState<MatchScoreResult | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState('t2_modern')
  const [templates,        setTemplates]        = useState<TemplateInfo[]>([])
  const [isEditMode,       setIsEditMode]       = useState(false)
  // LiveEditor's edit state — ID-stable ParsedCV (lib/cv.ts), not raw CvData.
  // toLiveEditorCvData() converts to the wire shape only where an API call
  // needs it (fetchMatchScore/renderPdf/saveCv); parseCv() converts back
  // whenever fresh cv_data JSON arrives from the backend.
  const [parsedCv,         setParsedCv]         = useState<ParsedCV | null>(null)
  const [isDirty,          setIsDirty]          = useState(false)
  const [isSaving,         setIsSaving]         = useState(false)
  // Both catch-blocks below used to fail completely silently — spinner
  // stops, nothing tells the user their edit wasn't persisted, and
  // handleEditorSave's failure is reachable from LiveEditor's own 30s
  // autosave timer, not just a manual click. These surface it the same way
  // downloadError already does for PDF download, just above.
  const [saveError,        setSaveError]        = useState<string | null>(null)
  const [isScoreLoading,   setIsScoreLoading]   = useState(false)
  // Draft mode — Copilot/LiveEditor edits only ever touch local state above.
  // hasUnsavedDraft tracks whether that local state has diverged from what's
  // actually persisted server-side; only handleSaveDraft() closes the gap.
  const [hasUnsavedDraft,  setHasUnsavedDraft]  = useState(false)
  const [isSavingDraft,    setIsSavingDraft]    = useState(false)
  const [saveDraftError,   setSaveDraftError]   = useState<string | null>(null)
  // Copilot state
  const [copilotPrompt,    setCopilotPrompt]    = useState('')
  // Ref mirrors copilotPrompt so handleCopilotSubmit always reads the latest
  // typed value even if the callback's closure captured a stale render cycle.
  const copilotPromptRef = useRef('')
  const [isCopilotBusy,    setIsCopilotBusy]    = useState(false)
  const [copilotError,     setCopilotError]     = useState('')
  const [copilotFeedback,  setCopilotFeedback]  = useState<{ status: 'warning' | 'rejected'; message: string } | null>(null)
  const [editHistory,      setEditHistory]      = useState<Array<{ cvData: Record<string, unknown>; pdfB64: string; matchScore: MatchScoreResult | null; chatHistory: { role: string; content: string }[] }>>([])
  const [chatHistory,      setChatHistory]      = useState<{ role: string; content: string }[]>([])


  const isLoading = phase === 'generating' || phase === 'revising' || phase === 'applying'

  const [loadingStatusIdx, setLoadingStatusIdx] = useState(0)
  useEffect(() => {
    if (!isLoading) { setLoadingStatusIdx(0); return }
    const id = setInterval(() => setLoadingStatusIdx(i => (i + 1) % A.loading_statuses.length), 1500)
    return () => clearInterval(id)
  }, [isLoading, A.loading_statuses.length])

  // ── Fetch templates on mount ──────────────────────────────────────────────
  useEffect(() => {
    fetchTemplates().then(setTemplates).catch(() => {})
  }, [])

  // ── Auto-load cached CV on mount ──────────────────────────────────────────
  useEffect(() => {
    fetchCachedCV(job.id).then(data => {
      if (!data || !data.cv_data) return
      setCvState({ cvData: data.cv_data, pdfB64: data.pdf_b64 ?? '' })
      setParsedCv(parseCv(data.cv_data).data)
      if (data.match_score)        setMatchScore(data.match_score)
      if (data.preferred_template) setSelectedTemplate(data.preferred_template)
      setPhase('preview')
    }).catch(err => {
      // Never swallow this. A cached CV that fails to load leaves the user on
      // the "no CV generated yet" empty state with no indication anything went
      // wrong — so the obvious next move is to regenerate, which costs one of
      // a small number of daily generations to rebuild a CV that already
      // exists. Failing quietly here is what makes that bill invisible.
      console.error('[ApplierPreview] cached CV failed to load:', err)
    })
  }, [job.id])

  // ── Core fetch helper ─────────────────────────────────────────────────────
  const callTailor = useCallback(async (
    supplementalAnswers?: Record<string, string>,
    force = false,
  ) => {
    setPhase('generating')
    setError('')
    setGkMessage('')

    try {
      const controller = new AbortController()
      // 180s, not the previous 90s. A single /tailor request can legitimately
      // chain several LLM calls (JD structuring -> tailoring -> optional
      // refinement -> match scoring), and when Gemini rate-limits, each one
      // falls back to Anthropic with its own retries. Observed real-world
      // worst case in this pipeline is ~145s, so 90s was aborting healthy
      // in-flight generations. Still below next.config.mjs's proxyTimeout
      // (300_000) so the browser, not the proxy, owns the deadline.
      const timeoutId  = setTimeout(() => controller.abort(), 180_000)
      let res: Response
      try {
        await ensureFreshToken()
        res = await fetch('/api/resumes/tailor', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body:    JSON.stringify({
            job_id:               job.id,
            supplemental_answers: supplementalAnswers ?? null,
            cv_locale:            cvLang,
            force,
          }),
          signal: controller.signal,
        })
      } finally {
        clearTimeout(timeoutId)
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(err.detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json()

      if (data.status === 'missing_data') {
        setMissingReqs(data.missing_data_requests ?? [])
        setAnswers({})
        setPhase('missing_data')
        return
      }

      // status === "ok"
      setCvState({ cvData: data.cv_data, pdfB64: data.pdf_b64 })
      setParsedCv(parseCv(data.cv_data).data)
      setIsDirty(false)
      setIsEditMode(false)
      setHasUnsavedDraft(false)   // /tailor persists its own output — this IS the saved baseline
      if (data.match_score)        setMatchScore(data.match_score)
      if (data.preferred_template) setSelectedTemplate(data.preferred_template)
      setMissingReqs([])
      setPhase('preview')
    } catch (e: unknown) {
      // An aborted fetch surfaces as DOMException('signal is aborted without
      // reason') — a raw internal string that meant nothing to the user and
      // gave no hint that retrying would help. Translate it before it can
      // reach the UI; every other error keeps its (server-authored, already
      // user-facing) detail message.
      const isAbort =
        (e instanceof DOMException && e.name === 'AbortError') ||
        (e instanceof Error && e.name === 'AbortError')

      setError(
        isAbort
          ? A.errors.timeout
          : e instanceof Error
            ? e.message
            : 'CV generation failed. Please try again.',
      )
      setPhase('idle')
    }
  }, [job.id, A.errors.timeout, cvLang])

  // ── Handlers ─────────────────────────────────────────────────────────────

  /**
   * Readiness guard — verifies the job object is fully processed before
   * firing the tailor endpoint.  Under the Zero-Click architecture this
   * should always pass; the guard is a defensive safety net for:
   *   • Race conditions where the modal opens before a status update propagates.
   *   • Stale props from a cached render that predates the pipeline completing.
   *
   * Uses feedJob (ApiFeedJob) because the lightweight Job type has no status
   * or jd_structured fields.
   */
  const handleGenerate = useCallback(() => {
    // A job is ready when the full pipeline has completed:
    //   • status === 'new'  — normal feed path (set by job_store._from_row)
    //   • score_is_proxy === false — set by the /analyze endpoint on the returned
    //     JobMatch before it has been read back from the DB; this is the reliable
    //     signal for jobs opened immediately after manual analysis.
    const pipelineDone =
      (feedJob.status === 'new' || feedJob.score_is_proxy === false) &&
      !!feedJob.jd_structured?.trim()

    console.info('[ApplierPreview] handleGenerate', {
      job_id:          feedJob.job_id,
      status:          feedJob.status,
      score_is_proxy:  feedJob.score_is_proxy,
      has_jd:          Boolean(feedJob.jd_structured),
      pipelineDone,
    })

    if (!pipelineDone) {
      setError(A.errors.still_loading)
      return
    }
    callTailor()
  }, [callTailor, feedJob, A.errors.still_loading])

  const handleSubmitInfo  = useCallback(() => callTailor(answers),         [callTailor, answers])
  const handleSkipInfo    = useCallback(() => callTailor({}),              [callTailor])

  const handleAnswerChange = useCallback((id: string, value: string) => {
    setAnswers(prev => ({ ...prev, [id]: value }))
  }, [])

  // ── B2C handlers ──────────────────────────────────────────────────────────

  const handleCvDataChange = useCallback((updated: ParsedCV) => {
    setParsedCv(updated)
    setIsDirty(true)
  }, [])

  const handleEditorReset = useCallback(() => {
    setParsedCv(prev => prev ? resetToOriginal(prev) : prev)
    setIsDirty(false)
  }, [])

  const handleEditorSave = useCallback(async () => {
    if (!parsedCv || isSaving) return
    setIsSaving(true)
    setIsScoreLoading(true)
    setSaveError(null)
    try {
      const editedCvData = toLiveEditorCvData(parsedCv)
      const [score, pdfB64] = await Promise.all([
        fetchMatchScore(job.id, editedCvData as Record<string, unknown>, false),
        renderPdf(editedCvData as Record<string, unknown>, selectedTemplate),
      ])
      setMatchScore(score)
      setCvState({ cvData: editedCvData as Record<string, unknown>, pdfB64 })
      // Saving commits the current edits as the new AI-original baseline —
      // re-parse so every field's originalValue/isAiGenerated resets to match.
      setParsedCv(parseCv(editedCvData).data)
      setIsDirty(false)
      setHasUnsavedDraft(true)   // local-only edit — not persisted until handleSaveDraft
      setIsEditMode(false)   // return to PDF view so updated score is front-and-center
    } catch (e: unknown) {
      // Stay in edit mode with isDirty still true — the edit itself is safe
      // (parsedCv is untouched), only the save attempt failed. Reachable
      // from LiveEditor's own 30s autosave timer, not just a manual click,
      // so this can appear without the user having just pressed anything.
      setSaveError(e instanceof Error ? e.message : A.errors.save_failed)
    } finally {
      setIsSaving(false)
      setIsScoreLoading(false)
    }
  }, [parsedCv, isSaving, job.id, selectedTemplate, A.errors.save_failed])

  const handleSaveDraft = useCallback(async () => {
    if (!cvState || isSavingDraft) return
    setIsSavingDraft(true)
    setSaveDraftError(null)
    try {
      await saveCv(job.id, cvState.cvData, matchScore as unknown as Record<string, unknown> | null)
      setHasUnsavedDraft(false)
    } catch (e: unknown) {
      // hasUnsavedDraft stays true — the banner (and this message) remain
      // visible until a retry succeeds, instead of silently disappearing.
      setSaveDraftError(e instanceof Error ? e.message : A.errors.save_draft_failed)
    } finally {
      setIsSavingDraft(false)
    }
  }, [cvState, isSavingDraft, job.id, matchScore, A.errors.save_draft_failed])

  // ── PDF download ─────────────────────────────────────────────────────────
  // Streams the binary from the server and saves it directly. The embedded
  // preview deliberately hides the browser's own PDF toolbar (see pdfDataUrl),
  // which also hides its download button — so without this control there is no
  // way for a user to actually get their CV out of the app.
  const [isDownloading, setIsDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  const handleDownloadPdf = useCallback(async () => {
    if (!cvState) return
    setIsDownloading(true)
    setDownloadError(null)
    try {
      await downloadCvPdf(cvState.cvData, selectedTemplate)
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : A.errors.download_failed)
    } finally {
      setIsDownloading(false)
    }
  }, [cvState, selectedTemplate, A.errors.download_failed])

  const handleSelectTemplate = useCallback(async (templateId: string) => {
    setSelectedTemplate(templateId)
    const data = parsedCv ? toLiveEditorCvData(parsedCv) : (cvState?.cvData as CvData | undefined)
    if (!data) return
    try {
      const pdfB64 = await renderPdf(data as Record<string, unknown>, templateId)
      setCvState(prev => prev ? { ...prev, pdfB64 } : null)
    } catch { /* leave existing preview intact */ }
  }, [parsedCv, cvState])

  const handleCopilotSubmit = useCallback(async () => {
    // Always read from the ref — guaranteed to hold the latest keystroke value
    // even if the closure was created before the last React render cycle.
    const promptToSend = copilotPromptRef.current.trim()
    if (!promptToSend || !cvState || isCopilotBusy) return
    setIsCopilotBusy(true)
    setCopilotError('')
    setCopilotFeedback(null)
    try {
      await ensureFreshToken()
      const res = await fetch('/api/resumes/copilot', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body:    JSON.stringify({
          job_id:       job.id,
          cv_data:      cvState.cvData,
          user_prompt:  promptToSend,
          chat_history: chatHistory.length > 0 ? chatHistory : null,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(err.detail ?? `HTTP ${res.status}`)
      }
      const data: CopilotResponse = await res.json()

      // warning / rejected — surface the agent's message as a chat bubble
      if (data.status === 'warning' || data.status === 'rejected') {
        setCopilotFeedback({ status: data.status, message: data.message ?? '' })
        return
      }

      // success — push current state onto history stack before overwriting
      const promptText = promptToSend
      setEditHistory(prev => [...prev, {
        cvData:      cvState.cvData,
        pdfB64:      cvState.pdfB64,
        matchScore:  matchScore,
        chatHistory: chatHistory,
      }])

      // append user turn + assistant acknowledgement to chat history
      setChatHistory(prev => [
        ...prev,
        { role: 'user',      content: promptText },
        { role: 'assistant', content: data.message ?? A.errors.edit_applied },
      ])

      const serverCvData = (data.cv_data ?? {}) as Record<string, unknown>

      // ── Optimistic pass ────────────────────────────────────────────────
      // data.patch is the RFC 6902 diff from the cv_data we SENT to the
      // cv_data the server returned (resumes.py recomputes it at the route
      // boundary, after static-section re-injection and any refine pass, so
      // it describes the final document). Applying it to the document we sent
      // touches only the paths that actually moved, instead of re-deriving the
      // whole CV from scratch.
      const optimistic = applyCvPatch(cvState.cvData, data.patch)
      if (optimistic.ok && optimistic.opsApplied > 0) {
        setCvState(prev => (prev ? { ...prev, cvData: optimistic.doc } : prev))
        setParsedCv(parseCv(optimistic.doc).data)
      }

      // ── Reconcile — the server is authoritative, unconditionally ────────
      // The optimistic document is kept ONLY when it is structurally identical
      // to the server's; otherwise the server's replaces it outright. This is
      // also the check that keeps an empty `patch` honest: `diff_cv()` returns
      // [] both when nothing changed and when the diff threw, and those look
      // the same on the wire. Comparing the result against cv_data is what
      // tells them apart — a no-op patch alongside a changed cv_data lands
      // here and reconciles, rather than being trusted as "no change".
      const converged = optimistic.ok && jsonEqual(optimistic.doc, serverCvData)
      if (converged) {
        setCvState({ cvData: optimistic.doc, pdfB64: data.pdf_b64 ?? '' })
      } else {
        if (!optimistic.ok) {
          console.warn('[copilot] patch did not apply locally — falling back to cv_data:', optimistic.error)
        } else if (optimistic.opsApplied > 0) {
          console.warn('[copilot] patch result diverged from cv_data — server wins')
        }
        setCvState({ cvData: serverCvData, pdfB64: data.pdf_b64 ?? '' })
        setParsedCv(parseCv(serverCvData).data)
      }

      setIsDirty(false)
      setHasUnsavedDraft(true)   // Copilot edits are draft-only — backend no longer auto-persists them
      copilotPromptRef.current = ''
      setCopilotPrompt('')
      setCopilotFeedback(null)

      // Always recompute the score from the freshly edited cv_data via the
      // dedicated endpoint.  Do not rely on the copilot response's match_score
      // field — if backend score computation failed silently (exception caught),
      // match_score is null and the old score would persist in the UI.
      setIsScoreLoading(true)
      fetchMatchScore(job.id, serverCvData, false)
        .then(score => setMatchScore(score))
        .catch(() => { if (data.match_score) setMatchScore(data.match_score) })
        .finally(() => setIsScoreLoading(false))
    } catch (e: unknown) {
      setCopilotError(e instanceof Error ? e.message : A.errors.copilot_failed)
    } finally {
      setIsCopilotBusy(false)
    }
    // `matchScore` is a real dependency, not lint appeasement. It is captured
    // above into editHistory as the PRE-edit score, which is what Undo must
    // restore alongside the pre-edit CV. Without it here the callback was only
    // rebuilt when cvState/chatHistory changed — both of which update
    // synchronously with the edit, while setMatchScore lands later from the
    // async fetchMatchScore below. So the closure kept the score from one edit
    // earlier: edit twice and Undo restored the right CV with the previous
    // edit's score.
  }, [cvState, isCopilotBusy, job.id, chatHistory, matchScore, A.errors.copilot_failed, A.errors.edit_applied])

  const handleUndo = useCallback(() => {
    setEditHistory(prev => {
      if (prev.length === 0) return prev
      const last = prev[prev.length - 1]
      setCvState({ cvData: last.cvData, pdfB64: last.pdfB64 })
      setParsedCv(parseCv(last.cvData).data)
      setMatchScore(last.matchScore)
      setChatHistory(last.chatHistory)
      setIsDirty(false)
      setCopilotFeedback(null)
      // Undoing back past the first Copilot edit restores the pre-edit
      // baseline (what's actually persisted) — nothing left to save.
      setHasUnsavedDraft(prev.length > 1)
      return prev.slice(0, -1)
    })
  }, [])

  const handleApprove = useCallback(async () => {
    setPhase('applying')
    // Fire mark-applied to backend (non-blocking — UI doesn't wait on it)
    markJobApplied(job.id).catch(() => { /* silently ignore; user can mark from feed */ })
    await new Promise(r => setTimeout(r, 700))
    onApplied?.(job.id)
    onClose()
  }, [job.id, onApplied, onClose])

  const handleRegenerate = useCallback(() => {
    setGkMessage('')
    setError('')
    setCvState(null)
    setMissingReqs([])
    setAnswers({})
    setParsedCv(null)
    setIsDirty(false)
    setIsEditMode(false)
    setIsScoreLoading(false)
    setMatchScore(null)
    callTailor(undefined, true)  // force=true bypasses the persisted cache
  }, [callTailor])

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(4px)' }}>
      <div className="relative flex w-full rounded-2xl overflow-hidden animate-modal-in"
        style={{
          height:     'min(90vh, 760px)',
          maxWidth:   'min(64rem, calc(100vw - 2rem))',
          background: TOKENS.color.surface,
          boxShadow:  '0 24px 64px rgba(15,23,42,0.22)',
        }}>

        {/* Close */}
        <button onClick={onClose}
          className="absolute top-3 right-3 z-10 w-7 h-7 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
          aria-label={A.close_preview}>
          <XIcon s={14} />
        </button>

        {/* ═══ LEFT PANE — 38% ═══════════════════════════════════════════════ */}
        {/* min-w-0 is load-bearing: without it, a flex item defaults to
            min-width:auto, so any child with intrinsic width wider than 38%
            (e.g. an unwrapped row of chips/badges) forces this pane wider
            than its box instead of scrolling/wrapping inside it — the modal's
            own overflow-hidden then clips whatever spilled past the left
            edge instead of containing it. */}
        <div className="flex flex-col w-[38%] min-w-0 shrink-0 overflow-y-auto overflow-x-hidden border-r"
          style={{ borderColor: TOKENS.color.line, padding: '24px 20px 24px 24px' }}>

          <div className="mb-1">
            <h2 className="text-[16px] font-semibold text-slate-900 tracking-tight">
              {A.title}
            </h2>
            <p className="text-[12.5px] text-slate-500 mt-0.5">
              {A.subtitle}
            </p>
          </div>

          <div className="my-4 border-t" style={{ borderColor: TOKENS.color.lineSoft }} />

          <JobInfoCard job={job} />

          {/* B2C — match score + template selector (preview phase only) */}
          {phase === 'preview' && matchScore && (
            <>
              <MatchScorePanel
                score={matchScore}
                isLoading={isLoading || isScoreLoading}
                baselineScore={job.score}
              />
              {templates.length > 0 && (
                <TemplateSelectorBar
                  templates={templates}
                  selectedId={selectedTemplate}
                  onSelect={handleSelectTemplate}
                  isLoading={isLoading}
                />
              )}

              {hasUnsavedDraft && (
                <div style={{
                  display: 'flex', flexDirection: 'column', gap: 6,
                  marginTop: 4, marginBottom: 12,
                  padding: '8px 12px', borderRadius: 10,
                  // oklch(...) pair matches ErrorBanner above and the copilot
                  // rejection banner below — this file's one soft-danger
                  // convention, not a one-off color.
                  border: saveDraftError ? '1px solid oklch(0.91 0.04 25)' : `1px solid ${TOKENS.color.line}`,
                  background: saveDraftError ? 'oklch(0.97 0.02 25)' : TOKENS.color.primarySoft,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                    <span style={{ fontSize: 11.5, color: TOKENS.color.ink2 }}>
                      {A.unsaved_draft}
                    </span>
                    <button
                      onClick={handleSaveDraft}
                      disabled={isSavingDraft}
                      style={{
                        flexShrink: 0,
                        fontSize: 11.5, fontWeight: 700,
                        color: '#fff', background: TOKENS.color.primary,
                        border: 'none', borderRadius: 8,
                        padding: '6px 12px',
                        cursor: isSavingDraft ? 'default' : 'pointer',
                        opacity: isSavingDraft ? 0.6 : 1,
                      }}
                    >
                      {isSavingDraft ? A.saving : A.save_to_profile}
                    </button>
                  </div>
                  {saveDraftError && (
                    <span style={{ fontSize: 11, color: TOKENS.color.danger }}>
                      ✕ {saveDraftError}
                    </span>
                  )}
                </div>
              )}
            </>
          )}

          {/* ── CV Copilot chat (preview phase, PDF view only) ── */}
          {phase === 'preview' && !isEditMode && (
            <div style={{
              borderRadius: 10,
              border: `1px solid ${TOKENS.color.line}`,
              background: 'white',
              padding: '11px 13px 12px',
              marginBottom: 12,
            }}>
              <p style={{ fontSize: 11, fontWeight: 700, color: TOKENS.color.primary, marginBottom: 7, letterSpacing: '0.4px', textTransform: 'uppercase' }}>
                CV Copilot
              </p>

              {/* Agent feedback bubble (warning / rejected) */}
              {copilotFeedback && (
                <div style={{
                  borderRadius: 7,
                  padding: '8px 10px',
                  marginBottom: 8,
                  fontSize: 11.5,
                  lineHeight: 1.5,
                  background: copilotFeedback.status === 'warning'
                    ? 'oklch(0.97 0.04 80)'
                    : 'oklch(0.97 0.02 25)',
                  border: `1px solid ${copilotFeedback.status === 'warning'
                    ? 'oklch(0.88 0.07 80)'
                    : 'oklch(0.90 0.05 25)'}`,
                  color: copilotFeedback.status === 'warning'
                    ? 'oklch(0.38 0.12 60)'
                    : TOKENS.color.danger,
                }}>
                  <span style={{ fontWeight: 700 }}>
                    {copilotFeedback.status === 'warning' ? '⚠ ' : '✕ '}
                  </span>
                  {copilotFeedback.message}
                </div>
              )}

              <textarea
                value={copilotPrompt}
                onChange={e => {
                  copilotPromptRef.current = e.target.value
                  setCopilotPrompt(e.target.value)
                  setCopilotError('')
                  if (copilotFeedback) setCopilotFeedback(null)
                }}
                // onInput fires on every character including Hebrew IME composition,
                // before React's synthetic onChange resolves the committed value.
                // This keeps the ref current during mid-composition keystrokes.
                onInput={e => { copilotPromptRef.current = (e.target as HTMLTextAreaElement).value }}
                // onCompositionEnd fires when the IME commits the composed word
                // (e.g. Hebrew, Arabic, CJK). Sync the ref with the final value.
                onCompositionEnd={e => { copilotPromptRef.current = (e.target as HTMLTextAreaElement).value }}
                onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleCopilotSubmit() }}
                placeholder={'e.g. "Make the first GO-OUT bullet more quantified"\n"Add Salesforce to skills"\n"Rewrite the summary for a PM role"'}
                rows={3}
                disabled={isCopilotBusy}
                style={{
                  width: '100%', display: 'block',
                  fontSize: 11.5, color: TOKENS.color.ink, lineHeight: 1.5,
                  background: isCopilotBusy ? 'oklch(0.97 0 0)' : 'oklch(0.98 0 0)',
                  border: `1px solid ${copilotError ? TOKENS.color.danger : TOKENS.color.line}`,
                  borderRadius: 7, padding: '7px 9px',
                  resize: 'none', outline: 'none',
                  fontFamily: 'inherit',
                  transition: 'opacity 0.15s',
                  opacity: isCopilotBusy ? 0.6 : 1,
                }}
              />
              {copilotError && (
                <p style={{ fontSize: 10.5, color: TOKENS.color.danger, marginTop: 4 }}>
                  {copilotError}
                </p>
              )}
              <button
                onClick={handleCopilotSubmit}
                disabled={!copilotPrompt.trim() || isCopilotBusy}
                style={{
                  marginTop: 7,
                  width: '100%', height: 32,
                  borderRadius: 20,
                  fontSize: 12, fontWeight: 600,
                  color: 'white',
                  background: isCopilotBusy ? TOKENS.color.muted : TOKENS.color.primary,
                  border: 'none', cursor: isCopilotBusy ? 'default' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                  transition: 'opacity 0.15s',
                  opacity: !copilotPrompt.trim() || isCopilotBusy ? 0.55 : 1,
                }}
              >
                {isCopilotBusy ? <><Spinner size={12} /> {A.copilot_editing}</> : A.apply_edit}
              </button>
              <p style={{ fontSize: 10, color: TOKENS.color.muted, marginTop: 6, textAlign: 'center' }}>
                ⌘↵ to submit · edits are saved automatically
              </p>

              {/* Undo — only visible after at least one successful edit */}
              {editHistory.length > 0 && (
                <button
                  onClick={handleUndo}
                  disabled={isCopilotBusy}
                  style={{
                    marginTop: 6,
                    width: '100%', height: 28,
                    borderRadius: 20,
                    fontSize: 11, fontWeight: 500,
                    color: TOKENS.color.ink2,
                    background: 'transparent',
                    border: `1px solid ${TOKENS.color.line}`,
                    cursor: isCopilotBusy ? 'default' : 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
                    opacity: isCopilotBusy ? 0.4 : 1,
                    transition: 'opacity 0.15s',
                  }}
                >
                  ↺ Undo last edit
                  <span style={{ fontSize: 10, color: TOKENS.color.muted }}>
                    ({editHistory.length})
                  </span>
                </button>
              )}
            </div>
          )}

          {/* Banners */}
          {error     && <ErrorBanner     message={error}     />}
          {gkMessage && <GatekeeperBanner message={gkMessage} />}

          {/* Missing-data form (sits above the spacer when active) */}
          {phase === 'missing_data' && missingReqs.length > 0 && (
            <MissingDataForm
              requests={missingReqs}
              answers={answers}
              onChange={handleAnswerChange}
              onSubmit={handleSubmitInfo}
              onSkip={handleSkipInfo}
              submitting={false}
            />
          )}

          <div className="flex-1" />

          {/* ── Action area ── */}

          {phase === 'idle' && (
            <div className="space-y-2.5">
              {/* Output language, decided here rather than in a settings screen.
                  It belongs next to the action it affects: this is the moment
                  the choice actually matters, and it is a per-job decision —
                  the same person may want a Hebrew CV for one employer and an
                  English one for the next. Rendered from LOCALES, so a new
                  language appears here without touching this file. */}
              <div>
                <p className="text-[11.5px] font-medium text-slate-500 mb-1.5">
                  {A.cv_language}
                </p>
                <div className="grid grid-cols-2 gap-2" role="group" aria-label={A.cv_language}>
                  {LOCALES.map(({ code, native }) => {
                    const active = cvLang === code
                    return (
                      <button
                        key={code}
                        type="button"
                        lang={code}
                        aria-pressed={active}
                        onClick={() => { cvLangTouched.current = true; setCvLang(code) }}
                        className={[
                          'h-9 rounded-lg text-[13px] font-semibold border transition-colors',
                          active
                            ? 'text-white border-transparent'
                            : 'bg-white text-slate-500 border-slate-200 hover:text-slate-700',
                        ].join(' ')}
                        style={active ? { background: TOKENS.color.primary } : undefined}
                      >
                        {native}
                      </button>
                    )
                  })}
                </div>
              </div>

              <button onClick={handleGenerate}
                className="w-full h-10 rounded-full text-[13.5px] font-semibold text-white flex items-center justify-center gap-2 transition active:scale-[0.98]"
                style={{ background: TOKENS.color.primary }}>
                <WandIcon s={15} /> {A.generate_cv}
              </button>
            </div>
          )}

          {phase === 'generating' && (
            <div className="flex items-center justify-center gap-2 h-10 text-[13px] text-slate-500">
              <Spinner size={16} /> {A.loading_statuses[loadingStatusIdx]}
            </div>
          )}

          {phase === 'missing_data' && (
            /* Form is rendered above — just show a subtle status hint here */
            <p className="text-center text-[11.5px] text-slate-400">
              {A.fill_form}
            </p>
          )}

          {(phase === 'preview' || phase === 'revising') && (
            <div className="space-y-2.5">
              {/* Edit / Preview toggle */}
              {/* Also disabled while Copilot is in flight. The Copilot panel
                  only renders in PDF view, so the user can never be *inside*
                  the editor when a request starts — but nothing stopped them
                  from entering it while one was pending, typing into a bullet,
                  and having the reconcile above replace parsedCv wholesale a
                  second later. Closing the door is the fix; there is no merge
                  that could recover the keystrokes after the fact. */}
              <button
                onClick={() => setIsEditMode(m => !m)}
                disabled={isLoading || isCopilotBusy}
                className="w-full h-9 rounded-full text-[12.5px] font-medium flex items-center justify-center gap-1.5 border transition disabled:opacity-50"
                style={{
                  color:      isEditMode ? TOKENS.color.primary : TOKENS.color.ink2,
                  borderColor: isEditMode ? TOKENS.color.primary : TOKENS.color.line,
                  background:  isEditMode ? TOKENS.color.primarySoft : 'white',
                }}
              >
                {isEditMode ? A.back_to_preview : A.edit_cv}
              </button>

              <button onClick={handleApprove} disabled={isLoading}
                className="w-full h-10 rounded-full text-[13.5px] font-semibold text-white flex items-center justify-center gap-1.5 transition disabled:opacity-60 active:scale-[0.98]"
                style={{ background: TOKENS.color.success }}>
                <CheckIcon s={15} /> {A.approve_apply}
              </button>

              {/* Same reason: regenerating clears cvState, which the pending
                  Copilot response would then write straight back over. */}
              <button onClick={handleRegenerate} disabled={isLoading || isCopilotBusy}
                className="w-full flex items-center justify-center gap-1 text-[11.5px] text-slate-400 hover:text-slate-600 transition disabled:opacity-40">
                <RefreshIcon s={12} /> {A.regenerate}
              </button>
            </div>
          )}

          {phase === 'applying' && (
            <div className="flex items-center justify-center gap-2 h-10 text-[13px] text-slate-500">
              <Spinner size={16} /> Submitting application…
            </div>
          )}
        </div>

        {/* ═══ RIGHT PANE — PDF preview, 62% ════════════════════════════════ */}
        <div className="flex-1 flex items-center justify-center relative"
          style={{ background: TOKENS.color.bg }}>

          {/* Loading overlay — keeps stale PDF visible during generation / revision / copilot */}
          {(phase === 'generating' || phase === 'revising' || isCopilotBusy) && (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3"
              style={{ background: 'rgba(248,250,252,0.82)', backdropFilter: 'blur(3px)' }}>
              <Spinner size={32} />
              <p className="text-[13px] text-slate-500 font-medium">
                {isCopilotBusy ? A.copilot_editing : phase === 'generating' ? A.loading_statuses[loadingStatusIdx] : A.evaluating}
              </p>
            </div>
          )}

          {/* Missing-data overlay — no PDF yet, show a placeholder message */}
          {phase === 'missing_data' && !cvState && (
            <div className="flex flex-col items-center gap-3 text-center px-10">
              <div className="w-14 h-14 rounded-2xl flex items-center justify-center"
                style={{ background: 'oklch(0.97 0.03 80)' }}>
                <InfoIcon s={24} />
              </div>
              <p className="text-[13.5px] font-semibold text-slate-700">
                {missingReqs.length === 1 ? A.one_detail : A.n_details.replace('{n}', String(missingReqs.length))}
              </p>
              <p className="text-[12.5px] text-slate-400 leading-relaxed max-w-xs">
                Answer the {missingReqs.length === 1 ? 'question' : 'questions'} on the left.
                Your answers are saved so you&apos;ll never be asked again.
              </p>
            </div>
          )}

          {cvState && !isEditMode && (
            <div className="absolute top-3 right-3 z-10 flex flex-col items-end gap-1.5">
              <button
                onClick={handleDownloadPdf}
                disabled={isDownloading}
                title={A.download_title}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12.5px] font-semibold
                           bg-white/95 backdrop-blur border border-slate-200 text-slate-700
                           hover:bg-white hover:border-teal-300 hover:text-teal-700
                           disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                style={{ boxShadow: '0 1px 2px rgba(15,23,42,.06), 0 4px 12px rgba(15,23,42,.06)' }}
              >
                {isDownloading ? A.preparing : A.download_pdf}
              </button>
              {downloadError && (
                <span className="max-w-[240px] text-right text-[11.5px] leading-snug text-rose-600
                                 bg-white/95 backdrop-blur px-2 py-1 rounded-md border border-rose-200">
                  {downloadError}
                </span>
              )}
            </div>
          )}

          {cvState && isEditMode && parsedCv ? (
            <LiveEditor
              cv={parsedCv}
              onChange={handleCvDataChange}
              onReset={handleEditorReset}
              isDirty={isDirty}
              isSaving={isSaving}
              onSave={handleEditorSave}
              saveError={saveError}
            />
          ) : cvState ? (
            <iframe
              key={cvState.pdfB64.slice(-16)}
              src={pdfDataUrl(cvState.pdfB64)}
              title={A.title}
              className="w-full h-full"
              style={{ border: 'none' }}
            />
          ) : null}

          {!cvState && phase !== 'missing_data' && phase !== 'generating' && (
            <EmptyPreview />
          )}
        </div>

      </div>
    </div>
  )
}
