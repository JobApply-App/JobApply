'use client'
import { useState, useEffect, useRef, useCallback } from 'react'
import type { VerifyChatEntry, VerifyChatStatus } from '@/lib/apiTypes'
import { sendVerifyChat } from '@/lib/api'
import { TOKENS } from '@/lib/tokens'

// ── Types ─────────────────────────────────────────────────────────────────────

type AgentEntry = {
  role:         'agent'
  question:     string
  gap_addressed: string
  raw:          string
}
type UserEntry = {
  role:    'user'
  content: string
}
type ChatEntry = AgentEntry | UserEntry

type Verdict = {
  status:               'verified' | 'failed'
  fit_score_adjustment: number
  new_fit_score:        number
  cv_advice:            string | null
  summary:              string
}

// ── Primitives ────────────────────────────────────────────────────────────────

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'spin 0.75s linear infinite' }}
    >
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-slate-400"
          style={{ animation: `thinking-dot 1.2s ease-in-out ${i * 0.2}s infinite` }}
        />
      ))}
      <style>{`
        @keyframes thinking-dot {
          0%,80%,100% { transform: translateY(0); opacity: 0.4; }
          40%          { transform: translateY(-4px); opacity: 1; }
        }
      `}</style>
    </div>
  )
}

// ── Chat bubbles ──────────────────────────────────────────────────────────────

function AgentBubble({ entry, index }: { entry: AgentEntry; index: number }) {
  return (
    <div className="flex items-start gap-3 max-w-[85%]">
      {/* Avatar */}
      <div
        className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold text-white mt-0.5"
        style={{ background: 'oklch(0.40 0.12 260)' }}
        title="Recruiter AI"
      >
        AI
      </div>
      <div>
        <div className="rounded-2xl rounded-tl-sm bg-slate-100 px-3.5 py-2.5">
          <p className="text-[13.5px] text-slate-900 leading-snug">{entry.question}</p>
        </div>
        <p className="text-[11px] text-slate-400 mt-1 ml-1 italic">
          Probing: {entry.gap_addressed}
        </p>
      </div>
    </div>
  )
}

function UserBubble({ entry }: { entry: UserEntry }) {
  return (
    <div className="flex justify-end">
      <div
        className="rounded-2xl rounded-tr-sm px-3.5 py-2.5 max-w-[80%]"
        style={{ background: TOKENS.color.primary }}
      >
        <p className="text-[13.5px] text-white leading-snug whitespace-pre-wrap">{entry.content}</p>
      </div>
    </div>
  )
}

function ThinkingBubble() {
  return (
    <div className="flex items-start gap-3">
      <div
        className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold text-white"
        style={{ background: 'oklch(0.40 0.12 260)' }}
      >
        AI
      </div>
      <div className="rounded-2xl rounded-tl-sm bg-slate-100 px-3.5 py-3">
        <ThinkingDots />
      </div>
    </div>
  )
}

// ── Verdict card ──────────────────────────────────────────────────────────────

function VerdictCard({
  verdict,
  originalScore,
  onClose,
}: {
  verdict:       Verdict
  originalScore: number
  onClose:       () => void
}) {
  const isVerified = verdict.status === 'verified'
  const hasAdj     = verdict.fit_score_adjustment < 0

  return (
    <div
      className={`rounded-2xl border p-4 mt-2 ${
        isVerified
          ? 'border-emerald-200 bg-emerald-50'
          : 'border-rose-200 bg-rose-50'
      }`}
    >
      {/* Status line */}
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-[18px] leading-none ${isVerified ? 'text-emerald-600' : 'text-rose-600'}`}>
          {isVerified ? '✓' : '✗'}
        </span>
        <div>
          <p className={`text-[14px] font-semibold ${isVerified ? 'text-emerald-800' : 'text-rose-800'}`}>
            {isVerified ? 'Experience Verified' : 'Gap Confirmed'}
          </p>
          {hasAdj && (
            <p className="text-[11.5px] text-rose-600 tabular-nums">
              Fit score: {originalScore.toFixed(0)} → <strong>{verdict.new_fit_score.toFixed(0)}</strong>
              {' '}({verdict.fit_score_adjustment.toFixed(0)})
            </p>
          )}
        </div>
      </div>

      {/* Summary */}
      <p className={`text-[12.5px] leading-relaxed mb-3 ${isVerified ? 'text-emerald-900' : 'text-rose-900'}`}>
        {verdict.summary}
      </p>

      {/* CV advice (verified only) */}
      {verdict.cv_advice && (
        <div className="rounded-2xl border border-teal-200 bg-teal-50 px-3.5 py-3 mb-3">
          <p className="text-[11.5px] font-semibold text-teal-800 mb-1 flex items-center gap-1.5">
            <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
            </svg>
            How to phrase this in your CV for a better ATS score
          </p>
          <p className="text-[12px] text-teal-900 leading-relaxed">{verdict.cv_advice}</p>
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={onClose}
          className="h-8 px-4 rounded-full text-[12.5px] font-medium border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 transition"
        >
          Close
        </button>
      </div>
    </div>
  )
}

// ── Modal ─────────────────────────────────────────────────────────────────────

export interface VerifyFitModalProps {
  jobId:           string
  jobTitle:        string
  company:         string
  currentFitScore: number
  onClose:         () => void
  onScoreUpdated:  (newFitScore: number) => void
}

export function VerifyFitModal({
  jobId,
  jobTitle,
  company,
  currentFitScore,
  onClose,
  onScoreUpdated,
}: VerifyFitModalProps) {
  const [chatLog,   setChatLog]   = useState<ChatEntry[]>([])
  const [draft,     setDraft]     = useState('')
  const [thinking,  setThinking]  = useState(false)
  const [done,      setDone]      = useState(false)
  const [verdict,   setVerdict]   = useState<Verdict | null>(null)
  const [error,     setError]     = useState('')

  const bottomRef   = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const startedRef  = useRef(false)

  // Auto-scroll to bottom whenever log or thinking state changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatLog, thinking, verdict])

  // Focus input when agent finishes thinking
  useEffect(() => {
    if (!thinking && !done) {
      textareaRef.current?.focus()
    }
  }, [thinking, done])

  // Kick off the first turn on mount (strict-mode safe)
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    sendTurn([])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Build the VerifyChatEntry[] from current chatLog + optional new user answer
  function buildHistory(log: ChatEntry[], userAnswer?: string): VerifyChatEntry[] {
    const entries: VerifyChatEntry[] = []
    for (const e of log) {
      if (e.role === 'agent') {
        entries.push({
          role:          'agent',
          content:       e.question,
          gap_addressed: e.gap_addressed,
          raw:           e.raw,
        })
      } else {
        entries.push({ role: 'user', content: e.content })
      }
    }
    if (userAnswer !== undefined) {
      entries.push({ role: 'user', content: userAnswer })
    }
    return entries
  }

  const sendTurn = useCallback(async (log: ChatEntry[], userAnswer?: string) => {
    setThinking(true)
    setError('')

    // Append user answer to local log immediately so it renders right away
    const optimisticLog: ChatEntry[] = userAnswer
      ? [...log, { role: 'user', content: userAnswer }]
      : log

    if (userAnswer) setChatLog(optimisticLog)

    try {
      const history = buildHistory(log, userAnswer)
      const res     = await sendVerifyChat(jobId, history)

      if (res.status === 'question') {
        const agentEntry: AgentEntry = {
          role:         'agent',
          question:     res.question!,
          gap_addressed: res.gap_addressed!,
          raw:          res.raw!,
        }
        setChatLog(prev => [...prev, agentEntry])
        setThinking(false)
      } else {
        // verdict
        const v: Verdict = {
          status:               res.status as 'verified' | 'failed',
          fit_score_adjustment: res.fit_score_adjustment ?? 0,
          new_fit_score:        res.new_fit_score ?? currentFitScore,
          cv_advice:            res.cv_advice ?? null,
          summary:              res.summary ?? '',
        }
        setVerdict(v)
        setDone(true)
        setThinking(false)
        if (v.fit_score_adjustment < 0) {
          onScoreUpdated(v.new_fit_score)
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
      setThinking(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, currentFitScore, onScoreUpdated])

  function handleSend() {
    const text = draft.trim()
    if (!text || thinking || done) return
    setDraft('')
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    sendTurn(chatLog, text)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      handleSend()
    }
  }

  function handleTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setDraft(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
  }

  const canSend = draft.trim().length >= 5 && !thinking && !done

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="relative w-full max-w-xl flex flex-col rounded-2xl bg-white shadow-floating animate-modal-in"
        style={{ height: 'min(92vh, 680px)', boxShadow: '0 24px 80px rgba(15,23,42,0.20)' }}
      >
        {/* ── Header ── */}
        <div className="shrink-0 border-b border-slate-100 px-5 py-3.5 flex items-start justify-between rounded-t-2xl">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="h-[18px] inline-flex items-center px-2 rounded-full text-[10.5px] font-semibold bg-amber-100 text-amber-700 tracking-wide uppercase">
                Verify Fit
              </span>
              {done && verdict && (
                <span className={`h-[18px] inline-flex items-center px-2 rounded-full text-[10.5px] font-semibold tracking-wide uppercase ${
                  verdict.status === 'verified'
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-rose-100 text-rose-700'
                }`}>
                  {verdict.status === 'verified' ? 'Verified' : 'Gap Found'}
                </span>
              )}
            </div>
            <p className="text-[14.5px] font-semibold text-slate-900 leading-tight">{jobTitle}</p>
            <p className="text-[12px] text-slate-500">{company}</p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 transition"
            aria-label="Close"
          >
            <svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* ── Chat area ── */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 min-h-0">
          {/* Opening hint — only before first agent message */}
          {chatLog.length === 0 && !thinking && (
            <p className="text-[12px] text-slate-400 text-center py-2">
              Starting investigation…
            </p>
          )}

          {chatLog.map((entry, i) =>
            entry.role === 'agent' ? (
              <AgentBubble key={i} entry={entry} index={i} />
            ) : (
              <UserBubble key={i} entry={entry} />
            )
          )}

          {thinking && <ThinkingBubble />}

          {verdict && (
            <VerdictCard
              verdict={verdict}
              originalScore={currentFitScore}
              onClose={onClose}
            />
          )}

          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[12.5px] text-rose-700 flex items-center justify-between">
              {error}
              <button
                onClick={() => sendTurn(chatLog)}
                className="ml-3 text-[12px] font-semibold underline shrink-0"
              >
                Retry
              </button>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* ── Input area ── */}
        {!done && (
          <div className="shrink-0 border-t border-slate-100 px-4 py-3 rounded-b-2xl bg-white">
            <div className="flex items-end gap-2">
              <textarea
                ref={textareaRef}
                rows={1}
                placeholder={thinking ? 'Waiting for next question…' : 'Answer specifically — include role, metrics, or project details…'}
                value={draft}
                onChange={handleTextareaChange}
                onKeyDown={handleKeyDown}
                disabled={thinking || done}
                className="flex-1 resize-none rounded-xl border border-slate-200 px-3.5 py-2.5 text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500/25 focus:border-teal-400 transition disabled:opacity-50 disabled:bg-slate-50 min-h-[40px] max-h-[120px]"
                style={{ lineHeight: '1.45' }}
              />
              <button
                onClick={handleSend}
                disabled={!canSend}
                title="Send (⌘ Enter)"
                className="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center text-white transition active:scale-95 disabled:opacity-35 disabled:pointer-events-none"
                style={{ background: TOKENS.color.primary }}
              >
                <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
            <p className="text-[10.5px] text-slate-400 mt-1.5 ml-1">
              {canSend ? '⌘ Enter to send' : thinking ? 'Analysing…' : 'Type your answer above'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
