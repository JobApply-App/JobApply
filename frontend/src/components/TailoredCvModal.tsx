'use client'

/**
 * TailoredCvModal — slide-in panel that shows an AI-generated CV brief
 * tailored to a specific job posting.
 *
 * Contents
 * ────────
 * • Positioning Summary   — 2-3 sentence pitch for this role
 * • Tailored Experience   — top 2-3 roles with rewritten bullets
 * • CV Copilot            — chat interface for inline text editing
 *                           (e.g. "make this more technical", "shorten bullet 2")
 *
 * Actions
 * ────────
 * • "Copy to Clipboard"    — plain-text export of the brief
 * • "Generate Full CV PDF" — opens the existing ApplierPreview flow
 * • Refresh                — re-runs the LLM, bypassing the cache
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { TOKENS } from '@/lib/tokens'
import type { ApiFeedJob } from '@/lib/apiTypes'
import type { TailoredSection, TailorBriefResponse } from '@/lib/apiTypes'
import { tailorCvForJob, editTailoredCv } from '@/lib/api'

// ── Icons ─────────────────────────────────────────────────────────────────────

function Spinner({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'spin 0.75s linear infinite', flexShrink: 0 }}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function XIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

function RefreshIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  )
}

function CopyIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

function CheckIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function WandIcon({ s = 15 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M15 4V2" /><path d="M15 16v-2" /><path d="M8 9h2" />
      <path d="M20 9h2" /><path d="M17.8 11.8 19 13" /><path d="M15 9h0" />
      <path d="M17.8 6.2 19 5" /><path d="m3 21 9-9" /><path d="M12.2 6.2 11 5" />
    </svg>
  )
}

function SendIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}

// ── Clipboard copy helper ─────────────────────────────────────────────────────

function buildClipboardText(brief: TailorBriefResponse, sections: TailoredSection[]): string {
  const lines: string[] = [
    `TAILORED CV BRIEF`,
    `${brief.job_title} at ${brief.company}`,
    `Generated: ${new Date(brief.generated_at).toLocaleDateString()}`,
    '',
    '═══════════════════════════════════════',
    'POSITIONING',
    '═══════════════════════════════════════',
    brief.positioning_summary,
    '',
  ]

  if (sections.length > 0) {
    lines.push('═══════════════════════════════════════')
    lines.push('TAILORED EXPERIENCE')
    lines.push('═══════════════════════════════════════')
    sections.forEach(section => {
      lines.push(`${section.role}  ·  ${section.company}  ·  ${section.dates}`)
      section.bullets.forEach(b => lines.push(`  • ${b}`))
      lines.push('')
    })
  }

  return lines.join('\n')
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PositioningSummary({ text }: { text: string }) {
  return (
    <div
      className="rounded-xl px-4 py-3 mb-5 border"
      style={{
        background: 'oklch(0.97 0.03 255)',
        borderColor: 'oklch(0.88 0.06 255)',
      }}
    >
      <p className="text-[12px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
        Positioning
      </p>
      <p className="text-[13.5px] text-slate-800 leading-relaxed">{text}</p>
    </div>
  )
}

function SectionCard({ section }: { section: TailoredSection }) {
  return (
    <div
      className="rounded-xl border border-slate-200 bg-white mb-3"
      style={{ boxShadow: '0 1px 3px rgba(15,23,42,0.06)' }}
    >
      <div className="px-4 py-2.5 border-b border-slate-100">
        <p className="text-[13px] font-semibold text-slate-800">{section.role}</p>
        <p className="text-[11.5px] text-slate-500 mt-0.5">
          <span className="font-medium text-slate-600">{section.company}</span>
          {section.dates && (
            <>
              <span className="text-slate-300 mx-1.5">·</span>
              {section.dates}
            </>
          )}
        </p>
      </div>
      <ul className="px-4 py-3 space-y-2">
        {section.bullets.map((bullet, i) => (
          <li key={i} className="flex gap-2 text-[12.5px] text-slate-700 leading-snug">
            <span className="mt-[3px] shrink-0 text-slate-400 select-none">•</span>
            <span>{bullet}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function TailoringSkeleton() {
  return (
    <div className="px-6 py-4 flex flex-col items-center justify-center min-h-[320px] gap-4">
      <div className="flex items-center gap-3 text-slate-500">
        <Spinner size={22} />
        <span className="text-[14px] font-medium">Analyzing fit and tailoring CV…</span>
      </div>
      <div className="w-full space-y-2.5 mt-4 animate-pulse">
        {[70, 90, 60, 85, 75].map((w, i) => (
          <div key={i}
            className="h-3 rounded-full bg-slate-100"
            style={{ width: `${w}%` }}
          />
        ))}
      </div>
      <p className="text-[11.5px] text-slate-400 text-center mt-2 max-w-xs">
        The AI is matching your experience against the job requirements.<br />
        This usually takes 5–15 seconds.
      </p>
    </div>
  )
}

// ── Error state ───────────────────────────────────────────────────────────────

function TailoringError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="px-6 py-8 flex flex-col items-center gap-3">
      <div
        className="rounded-xl border px-4 py-3 w-full text-center"
        style={{ background: 'oklch(0.97 0.03 25)', borderColor: 'oklch(0.88 0.08 25)' }}
      >
        <p className="text-[13px] font-semibold text-rose-700 mb-1">Generation failed</p>
        <p className="text-[12px] text-slate-600">{message}</p>
      </div>
      <button
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 h-8 px-4 rounded-full text-[12px] font-medium text-white transition active:scale-95"
        style={{ background: TOKENS.color.primary }}
      >
        <RefreshIcon /> Try again
      </button>
    </div>
  )
}

// ── CV Copilot chat ───────────────────────────────────────────────────────────

interface CopilotMessage {
  role:    'user' | 'assistant'
  content: string
}

const COPILOT_HINTS = [
  'Make bullet 1 more technical',
  'Shorten all bullets',
  'Add stronger action verbs',
  'Emphasize leadership',
]

interface CvCopilotProps {
  jobId:    string
  sections: TailoredSection[]
  onUpdate: (sections: TailoredSection[]) => void
}

function CvCopilot({ jobId, sections, onUpdate }: CvCopilotProps) {
  const [messages,    setMessages]    = useState<CopilotMessage[]>([])
  const [input,       setInput]       = useState('')
  const [isThinking,  setIsThinking]  = useState(false)
  const inputRef  = useRef<HTMLTextAreaElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to latest message
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isThinking])

  const send = useCallback(async (text?: string) => {
    const instruction = (text ?? input).trim()
    if (!instruction || isThinking) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: instruction }])
    setIsThinking(true)

    try {
      const result = await editTailoredCv(jobId, sections, instruction)
      onUpdate(result.sections)
      setMessages(prev => [...prev, { role: 'assistant', content: result.reply }])
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `⚠ Could not apply edit: ${msg}` },
      ])
    } finally {
      setIsThinking(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [input, isThinking, jobId, sections, onUpdate])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div
      className="border-t border-slate-200 mt-1"
      style={{ background: 'oklch(0.99 0.005 255)' }}
    >
      {/* Header */}
      <div className="px-4 pt-3 pb-1 flex items-center gap-1.5">
        <WandIcon s={13} />
        <p className="text-[11.5px] font-semibold text-slate-600 uppercase tracking-wider">
          CV Copilot
        </p>
        <p className="text-[11px] text-slate-400 ml-1">— edit these bullets with plain English</p>
      </div>

      {/* Hint chips — only when no messages yet */}
      {messages.length === 0 && (
        <div className="px-4 py-2 flex flex-wrap gap-1.5">
          {COPILOT_HINTS.map(hint => (
            <button
              key={hint}
              onClick={() => send(hint)}
              disabled={isThinking}
              className="inline-flex items-center h-6 px-2.5 rounded-full text-[11px] font-medium border border-slate-200 hover:border-slate-300 hover:bg-white transition disabled:opacity-40 text-slate-600"
            >
              {hint}
            </button>
          ))}
        </div>
      )}

      {/* Conversation history */}
      {messages.length > 0 && (
        <div
          ref={scrollRef}
          className="px-4 py-2 space-y-2 max-h-36 overflow-y-auto"
        >
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className="max-w-[85%] rounded-xl px-3 py-2 text-[12px] leading-snug"
                style={
                  msg.role === 'user'
                    ? { background: TOKENS.color.primary, color: '#fff' }
                    : { background: 'oklch(0.95 0.015 255)', color: 'oklch(0.30 0.04 255)' }
                }
              >
                {msg.content}
              </div>
            </div>
          ))}
          {isThinking && (
            <div className="flex justify-start">
              <div
                className="rounded-xl px-3 py-2 flex items-center gap-2"
                style={{ background: 'oklch(0.95 0.015 255)' }}
              >
                <Spinner size={13} />
                <span className="text-[11.5px] text-slate-500">Editing…</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Input row */}
      <div className="px-4 pb-3 pt-1.5 flex items-end gap-2">
        <textarea
          ref={inputRef}
          rows={1}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. make bullet 2 shorter…"
          disabled={isThinking}
          className="flex-1 resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-[12.5px] text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 disabled:opacity-50"
          style={{ minHeight: '36px', maxHeight: '80px', lineHeight: '1.4',
                   ['--tw-ring-color' as string]: TOKENS.color.primary }}
        />
        <button
          onClick={() => send()}
          disabled={!input.trim() || isThinking}
          className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-white transition active:scale-95 disabled:opacity-40 disabled:pointer-events-none"
          style={{ background: TOKENS.color.primary }}
          title="Send (Enter)"
        >
          {isThinking ? <Spinner size={14} /> : <SendIcon />}
        </button>
      </div>
    </div>
  )
}

// ── Main Modal ────────────────────────────────────────────────────────────────

interface TailoredCvModalProps {
  job:           ApiFeedJob
  onClose:       () => void
  /** Opens the full ApplierPreview PDF generation flow. */
  onGeneratePdf: (job: ApiFeedJob) => void
}

export function TailoredCvModal({ job, onClose, onGeneratePdf }: TailoredCvModalProps) {
  type Phase = 'loading' | 'ready' | 'error'

  const [phase,    setPhase]    = useState<Phase>('loading')
  const [brief,    setBrief]    = useState<TailorBriefResponse | null>(null)
  // Live sections — may diverge from brief.tailored_sections after Copilot edits
  const [sections, setSections] = useState<TailoredSection[]>([])
  const [errorMsg, setErrorMsg] = useState('')
  const [copied,   setCopied]   = useState(false)

  const load = useCallback(async (force = false) => {
    setPhase('loading')
    setErrorMsg('')
    try {
      const result = await tailorCvForJob(job.job_id, force)
      setBrief(result)
      setSections(result.tailored_sections)
      setPhase('ready')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setErrorMsg(msg)
      setPhase('error')
    }
  }, [job.job_id])

  // Trigger on mount
  useEffect(() => { load(false) }, [load])

  // Copy to clipboard — always uses latest (possibly Copilot-edited) sections
  const handleCopy = useCallback(async () => {
    if (!brief) return
    const text = buildClipboardText(brief, sections)
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API unavailable — silent fail
    }
  }, [brief, sections])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <>
      {/* Backdrop — Meridian V2 §3.2 scrim */}
      <div
        className="fixed inset-0 z-40 bg-slate-900/55 backdrop-blur-[4px]"
        onClick={onClose}
      />

      {/* Panel — slides in from the right */}
      <div
        className="fixed inset-y-0 right-0 z-50 flex flex-col bg-slate-50 shadow-floating"
        style={{ width: 'min(600px, 100vw)' }}
      >
        {/* ── Header ───────────────────────────────────────────────────────── */}
        <div
          className="flex items-start justify-between px-5 py-4 border-b border-slate-200 bg-white shrink-0"
          style={{ boxShadow: '0 1px 4px rgba(15,23,42,0.06)' }}
        >
          <div className="min-w-0 flex-1 pr-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className="inline-flex items-center gap-1 text-[10.5px] font-semibold px-2 h-5 rounded-full"
                style={{ background: TOKENS.color.primarySoft, color: TOKENS.color.primary }}
              >
                <WandIcon s={10} /> AI Brief
              </span>
              {brief?.cached && (
                <span className="text-[10.5px] text-slate-400 font-medium">· cached</span>
              )}
            </div>
            <h2 className="text-[15px] font-bold text-slate-900 mt-1 leading-tight truncate">
              {job.title}
            </h2>
            <p className="text-[12.5px] text-slate-500 mt-0.5 truncate">
              <span className="font-medium text-slate-700">{job.company}</span>
              {job.location && (
                <>
                  <span className="text-slate-300 mx-1.5">·</span>
                  {job.location}
                </>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-slate-500 hover:bg-slate-100 transition"
            title="Close"
          >
            <XIcon />
          </button>
        </div>

        {/* ── Content area ─────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto">
          {phase === 'loading' && <TailoringSkeleton />}

          {phase === 'error' && (
            <TailoringError message={errorMsg} onRetry={() => load(true)} />
          )}

          {phase === 'ready' && brief && (
            <>
              <div className="px-5 py-5">
                <PositioningSummary text={brief.positioning_summary} />

                {sections.length > 0 && (
                  <div className="mb-4">
                    <p className="text-[12px] font-semibold text-slate-500 uppercase tracking-wider mb-3">
                      📝 Tailored Experience
                    </p>
                    {sections.map((section, i) => (
                      <SectionCard key={i} section={section} />
                    ))}
                  </div>
                )}

                {/* Thin JD notice if no JD was available */}
                {(!job.jd_text || job.jd_text.trim().length < 80) && (
                  <div
                    className="rounded-lg border px-3 py-2.5 mb-2"
                    style={{ background: 'oklch(0.97 0.03 75)', borderColor: 'oklch(0.88 0.08 75)' }}
                  >
                    <p className="text-[11.5px] text-amber-700">
                      <strong>Note:</strong> The full job description hasn&apos;t been fetched yet — this
                      brief is based on available metadata. Fetch the JD first for a more precise
                      tailoring.
                    </p>
                  </div>
                )}
              </div>

              {/* CV Copilot — pinned below the experience cards */}
              {sections.length > 0 && (
                <CvCopilot
                  jobId={job.job_id}
                  sections={sections}
                  onUpdate={setSections}
                />
              )}
            </>
          )}
        </div>

        {/* ── Footer actions ────────────────────────────────────────────────── */}
        <div
          className="shrink-0 border-t border-slate-200 bg-white px-5 py-3 flex items-center justify-between gap-3"
          style={{ boxShadow: '0 -1px 4px rgba(15,23,42,0.04)' }}
        >
          <div className="flex items-center gap-2">
            {/* Copy to clipboard */}
            <button
              onClick={handleCopy}
              disabled={phase !== 'ready' || !brief}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-[12px] font-medium border border-slate-200 hover:bg-slate-50 transition disabled:opacity-40 disabled:pointer-events-none text-slate-600"
            >
              {copied ? <><CheckIcon /> Copied!</> : <><CopyIcon /> Copy</>}
            </button>

            {/* Refresh */}
            <button
              onClick={() => load(true)}
              disabled={phase === 'loading'}
              title="Re-generate brief (bypasses cache)"
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-[12px] font-medium border border-slate-200 hover:bg-slate-50 transition disabled:opacity-40 disabled:pointer-events-none text-slate-500"
            >
              <RefreshIcon /> Refresh
            </button>
          </div>

          {/* Generate Full CV PDF */}
          <button
            onClick={() => { onClose(); onGeneratePdf(job) }}
            className="inline-flex items-center gap-1.5 h-8 px-4 rounded-full text-[12.5px] font-semibold text-white transition active:scale-95"
            style={{ background: TOKENS.color.primary }}
          >
            <WandIcon s={13} /> Generate Full CV
          </button>
        </div>
      </div>
    </>
  )
}
