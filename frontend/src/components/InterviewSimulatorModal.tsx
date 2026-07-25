'use client'
import { useCallback, useEffect, useState } from 'react'
import type { ApiFeedJob } from '@/lib/apiTypes'
import { evaluateInterviewAnswer, generateInterviewQuestion } from '@/lib/api'

// ── Ariel Mock Interview Simulator (JOB-61) ───────────────────────────────────
//
// One question at a time, grounded in this job's JD and the user's known gaps.
// Flow: open → Ariel asks a targeted question → user types an answer →
// submit → constructive feedback → revise the answer or take a new question.
// Stateless by design: nothing is persisted; closing the modal ends the round.

function SpinnerIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 0.8s linear infinite' }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-1.5">
      {children}
    </p>
  )
}

/** Generated-content marker (Meridian V2 §6.1) — amethyst left border + bg-ja-aiSubtle (Ariel wrote this). */
function ArielBlock({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg px-4 py-3 bg-ja-aiSubtle border border-l-2 border-slate-200 border-l-ja-ai">
      {children}
    </div>
  )
}

function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="rounded-lg px-4 py-4 space-y-2.5 bg-slate-50 border border-slate-200" aria-busy="true">
      <div className="flex items-center gap-2 mb-1 text-violet-600">
        <SpinnerIcon s={14} />
        <span className="text-[12px] font-medium">{label}</span>
      </div>
      {[85, 60].map((w, i) => (
        <div key={i} className="h-2.5 rounded-full animate-pulse bg-slate-200"
          style={{ width: `${w}%`, animationDelay: `${i * 100}ms` }} />
      ))}
    </div>
  )
}

function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 flex items-center justify-between gap-3">
      <p className="text-[12.5px] text-rose-700">{message}</p>
      <button onClick={onRetry} className="shrink-0 text-[11.5px] font-medium text-rose-700 underline underline-offset-2">
        Retry
      </button>
    </div>
  )
}

interface InterviewSimulatorModalProps {
  job:     ApiFeedJob
  onClose: () => void
}

export function InterviewSimulatorModal({ job, onClose }: InterviewSimulatorModalProps) {
  const [question,     setQuestion]     = useState('')
  const [answer,       setAnswer]       = useState('')
  const [feedback,     setFeedback]     = useState('')
  const [loadingQ,     setLoadingQ]     = useState(true)
  const [evaluating,   setEvaluating]   = useState(false)
  const [questionErr,  setQuestionErr]  = useState<string | null>(null)
  const [evalErr,      setEvalErr]      = useState<string | null>(null)
  const [rounds,       setRounds]       = useState(0)   // questions asked this session

  const fetchQuestion = useCallback(async () => {
    setLoadingQ(true)
    setQuestionErr(null)
    setFeedback('')
    setEvalErr(null)
    setAnswer('')
    try {
      const res = await generateInterviewQuestion(job.job_id)
      setQuestion(res.question)
      setRounds(r => r + 1)
    } catch (e) {
      setQuestionErr(e instanceof Error ? e.message : 'Could not generate a question.')
    } finally {
      setLoadingQ(false)
    }
  }, [job.job_id])

  // Ariel opens with a question — that's the whole point of the modal.
  useEffect(() => { fetchQuestion() }, [fetchQuestion])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const submitAnswer = useCallback(async () => {
    const trimmed = answer.trim()
    if (!trimmed || evaluating || !question) return
    setEvaluating(true)
    setEvalErr(null)
    try {
      const res = await evaluateInterviewAnswer(job.job_id, question, trimmed)
      setFeedback(res.feedback)
    } catch (e) {
      setEvalErr(e instanceof Error ? e.message : 'Evaluation failed. Please try again.')
    } finally {
      setEvaluating(false)
    }
  }, [answer, evaluating, question, job.job_id])

  const reviseAnswer = useCallback(() => {
    setFeedback('')
    setEvalErr(null)
  }, [])

  const hasFeedback = Boolean(feedback)

  return (
    <>
      {/* Backdrop — Meridian V2 §3.2 scrim */}
      <div className="fixed inset-0 z-40 bg-slate-900/55 backdrop-blur-[4px]" onClick={onClose} />

      {/* Panel */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div
          className="w-full max-w-xl max-h-[92vh] overflow-y-auto rounded-2xl bg-white shadow-floating pointer-events-auto flex flex-col animate-modal-in"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b border-slate-100">
            <div className="min-w-0 flex-1 pr-3">
              <div className="flex items-center gap-1.5 mb-1">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-violet-500 shrink-0" />
                <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                  Ariel · Mock Interview
                </p>
                {rounds > 0 && (
                  <span className="text-[10px] font-semibold text-slate-300 tabular-nums ml-1">
                    Q{rounds}
                  </span>
                )}
              </div>
              <h3 className="text-[15px] font-bold text-slate-900 leading-snug truncate">
                {job.title}
              </h3>
              <p className="text-[12px] text-slate-400 mt-0.5 truncate">{job.company}</p>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition"
            >
              <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 space-y-4">

            {/* ── Question ─────────────────────────────────────────────────── */}
            <div>
              <SectionLabel>Question</SectionLabel>
              {loadingQ ? (
                <LoadingBlock label="Ariel is preparing a targeted question…" />
              ) : questionErr ? (
                <ErrorBlock message={questionErr} onRetry={fetchQuestion} />
              ) : (
                <ArielBlock>
                  <p dir="auto" className="text-[13px] text-slate-700 leading-relaxed [unicode-bidi:plaintext] text-start">
                    {question}
                  </p>
                </ArielBlock>
              )}
            </div>

            {/* ── Answer ───────────────────────────────────────────────────── */}
            {!loadingQ && !questionErr && (
              <div>
                <SectionLabel>Your Answer</SectionLabel>
                <textarea
                  value={answer}
                  onChange={e => setAnswer(e.target.value)}
                  placeholder="Answer as you would in the real interview — concrete situation, action, outcome…"
                  rows={5}
                  disabled={evaluating || hasFeedback}
                  dir="auto"
                  className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3.5 py-3 text-[13px] leading-relaxed text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500/25 focus:border-teal-400 transition disabled:opacity-60 disabled:bg-slate-50 [unicode-bidi:plaintext] text-start"
                />
                {!hasFeedback && (
                  <div className="flex items-center justify-between mt-1.5">
                    <span className="text-[11px] text-slate-400 tabular-nums">
                      {answer.trim() ? `${answer.trim().split(/\s+/).filter(Boolean).length} words` : ''}
                    </span>
                    <button
                      onClick={submitAnswer}
                      disabled={evaluating || !answer.trim()}
                      className="inline-flex items-center gap-1.5 h-8 px-4 rounded-lg text-[12.5px] font-semibold text-white bg-ja-primary hover:bg-ja-primaryHover transition active:scale-[0.97] disabled:opacity-40 disabled:pointer-events-none"
                    >
                      {evaluating ? <><SpinnerIcon s={12} /> Evaluating…</> : 'Submit Answer'}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* ── Evaluation ───────────────────────────────────────────────── */}
            {evaluating && <LoadingBlock label="Ariel is evaluating your answer…" />}
            {evalErr && <ErrorBlock message={evalErr} onRetry={submitAnswer} />}
            {hasFeedback && (
              <div>
                <SectionLabel>Ariel&apos;s Feedback</SectionLabel>
                <ArielBlock>
                  <p dir="auto" className="text-[13px] text-slate-700 leading-relaxed whitespace-pre-wrap [unicode-bidi:plaintext] text-start">
                    {feedback}
                  </p>
                </ArielBlock>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-5 pb-5 pt-1 flex items-center justify-between border-t border-slate-100 mt-1 pt-4">
            <button
              onClick={onClose}
              className="h-8 px-4 rounded-lg text-[12.5px] font-medium text-slate-600 border border-slate-200 hover:bg-slate-50 transition"
            >
              End Session
            </button>
            {hasFeedback && (
              <div className="flex items-center gap-2">
                <button
                  onClick={reviseAnswer}
                  className="h-8 px-3.5 rounded-lg text-[12.5px] font-medium text-slate-600 border border-slate-200 hover:bg-slate-50 transition"
                >
                  Revise Answer
                </button>
                <button
                  onClick={fetchQuestion}
                  className="inline-flex items-center gap-1.5 h-8 px-4 rounded-lg text-[12.5px] font-semibold text-white bg-ja-primary hover:bg-ja-primaryHover transition active:scale-[0.97]"
                >
                  Next Question →
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
