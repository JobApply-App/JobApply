'use client'
import { useState, useRef, useEffect, useCallback } from 'react'
import { TOKENS } from '@/lib/tokens'
import type { InterviewSession, ConfidenceClaim } from '@/lib/apiTypes'
import {
  startInterview,
  sendInterviewMessage,
  uploadVerificationDocument,
  getInterviewSession,
  resumeInterviewSession,
  type StartInterviewContext,
} from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'
import { resolveDisplayName } from '@/lib/nameUtils'

const SESSION_STORAGE_KEY = 'profile_interview_session_id'

// ── Markdown sanitizer ────────────────────────────────────────────────────────
// The backend is instructed to output plain text only, but LLMs occasionally
// slip markdown syntax through. This strips all formatting symbols before render
// so the user never sees raw asterisks, long dashes, or header hashes in chat.

function sanitizeText(raw: string): string {
  return raw
    // Bold: **text** → text
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    // Bold: __text__ → text
    .replace(/__([^_]+)__/g, '$1')
    // Italic: *text* (not a bullet * at line start) → text
    .replace(/\*([^*\s][^*\n]*[^*\s]|[^*\s])\*/g, '$1')
    // Italic: _text_ → text
    .replace(/_([^_\s][^_\n]*[^_\s]|[^_\s])_/g, '$1')
    // Em dash (—) → spaced hyphen
    .replace(/—/g, ' - ')
    // Markdown headers (## Title, ### Title …) → title only
    .replace(/^#{1,6}\s+/gm, '')
    // Bullet asterisks (* item) at line start → plain line (no symbol)
    .replace(/^\*\s+/gm, '')
    // Collapse any triple+ newlines introduced by stripping to double
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

// ── Confidence helpers ────────────────────────────────────────────────────────

function confColor(score: number): string {
  if (score >= 100) return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (score >= 60)  return 'text-teal-700 bg-teal-50 border-teal-200'
  if (score >= 30)  return 'text-amber-700 bg-amber-50 border-amber-200'
  return 'text-red-700 bg-red-50 border-red-200'
}

function confLabel(score: number, status: string): string {
  if (score >= 100) return '✓ Verified'
  if (status === 'incomplete') return '⚠ Incomplete'
  if (score >= 60)  return '~ Consistent'
  return '? Unverified'
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ConfidenceBadge({ claim }: { claim: ConfidenceClaim }) {
  const color = confColor(claim.score)
  const label = confLabel(claim.score, claim.status)
  return (
    <span className={`inline-flex items-center gap-1 h-5 px-2 rounded-full text-[10.5px] font-semibold border ${color}`}>
      {label} {claim.score}%
    </span>
  )
}

function SpinnerIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 0.8s linear infinite', flexShrink: 0 }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function SendIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}

function UploadIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 16 12 12 8 16" /><line x1="12" y1="12" x2="12" y2="21" />
      <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3" />
    </svg>
  )
}

function PaperclipIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  )
}

// ── Draft Profile Panel ───────────────────────────────────────────────────────

interface DraftPanelProps {
  session:        InterviewSession
  onUploadRequest:(claim: string, docType: string) => void
}

function DraftPanel({ session, onUploadRequest }: DraftPanelProps) {
  const { draft_profile, confidence_map } = session
  if (!draft_profile) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center px-6 gap-3">
        <div className="w-12 h-12 rounded-2xl bg-slate-100 flex items-center justify-center text-2xl">📋</div>
        <p className="text-[13px] font-semibold text-slate-700">Profile Being Built</p>
        <p className="text-[12px] text-slate-400 leading-relaxed">
          As you chat, your profile will appear here with confidence scores for each claim.
        </p>
      </div>
    )
  }

  const edu = (draft_profile.education as any[]) || []
  const exp = (draft_profile.experience as any[]) || []
  const mil = draft_profile.military as Record<string, any> | null
  const skills = (draft_profile.skills as string[]) || []

  const claimFor = (key: string): ConfidenceClaim | null =>
    confidence_map[key] ?? null

  return (
    <div className="p-4 space-y-5 overflow-y-auto h-full">
      <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Profile Draft</p>

      {/* Education */}
      {edu.length > 0 && (
        <section>
          <p className="text-[11.5px] font-semibold text-slate-600 mb-2">Education</p>
          <div className="space-y-2">
            {edu.map((e: any, idx: number) => {
              const claim = claimFor(`education.${idx}`)
              const label = e.degree || e.certification || 'Degree'
              const inst  = e.institution || '?'
              const dates = [e.start_year, e.end_year].filter(Boolean).join('–') || '?'
              const needsDoc = claim && claim.score < 60 && (label || inst)
              return (
                <div key={idx} className="rounded-lg border border-slate-100 bg-white px-3 py-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[12.5px] font-semibold text-slate-800 truncate">{label}</p>
                      <p className="text-[11.5px] text-slate-500">{inst} · {dates}</p>
                      {e.honors && <p className="text-[11px] text-emerald-600 mt-0.5">{e.honors}</p>}
                      {(claim?.missing_details ?? []).length > 0 && (
                        <p className="text-[11px] text-amber-600 mt-0.5">
                          Missing: {(claim?.missing_details ?? []).join(', ')}
                        </p>
                      )}
                    </div>
                    {claim && <ConfidenceBadge claim={claim} />}
                  </div>
                  {needsDoc && (
                    <button
                      onClick={() => onUploadRequest(
                        `${label} from ${inst}`,
                        'transcript'
                      )}
                      className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-violet-700 hover:text-violet-900"
                    >
                      <UploadIcon s={11} /> Upload transcript to verify
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Experience */}
      {exp.length > 0 && (
        <section>
          <p className="text-[11.5px] font-semibold text-slate-600 mb-2">Experience</p>
          <div className="space-y-2">
            {exp.map((e: any, idx: number) => {
              const claim  = claimFor(`experience.${idx}`)
              const role   = e.role || '?'
              const co     = e.company || '?'
              const start  = e.start_date || '?'
              const end    = e.end_date || '?'
              const needsDoc = claim && claim.score < 30
              return (
                <div key={idx} className="rounded-lg border border-slate-100 bg-white px-3 py-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[12.5px] font-semibold text-slate-800 truncate">{role}</p>
                      <p className="text-[11.5px] text-slate-500">{co} · {start}–{end}</p>
                      {e.team_size && (
                        <p className="text-[11px] text-slate-400">Team: {e.team_size}</p>
                      )}
                      {(claim?.missing_details ?? []).length > 0 && (
                        <p className="text-[11px] text-amber-600 mt-0.5">
                          Missing: {(claim?.missing_details ?? []).join(', ')}
                        </p>
                      )}
                    </div>
                    {claim && <ConfidenceBadge claim={claim} />}
                  </div>
                  {needsDoc && (
                    <button
                      onClick={() => onUploadRequest(
                        `${role} at ${co}`,
                        'employment_letter'
                      )}
                      className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-violet-700 hover:text-violet-900"
                    >
                      <UploadIcon s={11} /> Upload employment letter to verify
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Military */}
      {mil && mil.role && (
        <section>
          <p className="text-[11.5px] font-semibold text-slate-600 mb-2">Military Service</p>
          <div className="rounded-lg border border-slate-100 bg-white px-3 py-2.5">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-[12.5px] font-semibold text-slate-800">{mil.role}</p>
                <p className="text-[11.5px] text-slate-500">
                  {mil.unit || '?'} · {mil.start || '?'}–{mil.end || '?'}
                </p>
                {confidence_map['military']?.missing_details?.length > 0 && (
                  <p className="text-[11px] text-amber-600 mt-0.5">
                    Missing: {confidence_map['military'].missing_details.join(', ')}
                  </p>
                )}
              </div>
              {confidence_map['military'] && <ConfidenceBadge claim={confidence_map['military']} />}
            </div>
            {confidence_map['military'] && confidence_map['military'].score < 60 && (
              <button
                onClick={() => onUploadRequest(`${mil.role} at ${mil.unit}`, 'military_record')}
                className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-violet-700 hover:text-violet-900"
              >
                <UploadIcon s={11} /> Upload discharge record to verify
              </button>
            )}
          </div>
        </section>
      )}

      {/* Skills */}
      {skills.length > 0 && (
        <section>
          <p className="text-[11.5px] font-semibold text-slate-600 mb-2">Skills Mentioned</p>
          <div className="flex flex-wrap gap-1.5">
            {skills.map((sk: string) => (
              <span key={sk} className="h-6 px-2.5 rounded-full bg-slate-100 text-slate-700 text-[11.5px] font-medium border border-slate-200">
                {sk}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Overall completion */}
      <section className="pt-2 border-t border-slate-100">
        <p className="text-[11px] text-slate-400 text-center">
          {Object.keys(confidence_map).length} claim(s) extracted ·{' '}
          {Object.values(confidence_map).filter(c => c.score >= 100).length} verified
        </p>
      </section>
    </div>
  )
}

// ── Upload Zone (modal) ───────────────────────────────────────────────────────

interface UploadZoneProps {
  sessionId:  string
  claim:      string
  docType:    string
  onVerified: (result: { verification: { status: string; confidence: number | null; match_notes: string } }) => void
  onClose:    () => void
}

function UploadZone({ sessionId, claim, docType, onVerified, onClose }: UploadZoneProps) {
  const [uploading, setUploading] = useState(false)
  const [result,    setResult]    = useState<null | { status: string; match_notes: string }>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback(async (file: File) => {
    setUploading(true)
    try {
      const res = await uploadVerificationDocument(sessionId, claim, docType, file)
      setResult(res.verification)
      onVerified(res as any)
    } catch {
      setResult({ status: 'unreadable', match_notes: 'Upload failed. Please try again.' })
    } finally {
      setUploading(false)
    }
  }, [sessionId, claim, docType, onVerified])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(4px)' }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-md rounded-2xl bg-white shadow-floating p-6 flex flex-col gap-4 animate-modal-in">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[14px] font-semibold text-slate-900">Upload Verification Document</p>
            <p className="text-[12px] text-slate-500 mt-0.5">Claim: <em>{claim}</em></p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-lg leading-none">✕</button>
        </div>

        {!result ? (
          <div
            onDrop={onDrop}
            onDragOver={e => e.preventDefault()}
            onClick={() => inputRef.current?.click()}
            className="border-2 border-dashed border-slate-200 rounded-xl p-8 flex flex-col items-center gap-3 cursor-pointer hover:border-violet-300 hover:bg-violet-50 transition"
          >
            {uploading ? (
              <><SpinnerIcon s={24} /><p className="text-[13px] text-slate-500">Analysing document…</p></>
            ) : (
              <>
                <UploadIcon s={28} />
                <p className="text-[13px] font-medium text-slate-700">Drop PDF or image here</p>
                <p className="text-[11.5px] text-slate-400">PDF · PNG · JPG · WEBP — max 10 MB</p>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.webp"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
            />
          </div>
        ) : (
          <div className={`rounded-xl border p-4 ${
            result.status === 'verified'   ? 'border-emerald-200 bg-emerald-50' :
            result.status === 'partial'    ? 'border-teal-200 bg-teal-50' :
            result.status === 'failed'     ? 'border-red-200 bg-red-50' :
                                             'border-slate-200 bg-slate-50'
          }`}>
            <p className="text-[13px] font-semibold text-slate-800 mb-1">
              {result.status === 'verified'   ? '✓ Verified!' :
               result.status === 'partial'    ? '~ Partially verified' :
               result.status === 'failed'     ? '✗ Not verified' :
                                                '⚠ Could not read document'}
            </p>
            <p className="text-[12.5px] text-slate-600">{result.match_notes}</p>
          </div>
        )}

        <button onClick={onClose} className="text-[12px] text-slate-400 hover:text-slate-600 text-center">
          {result ? 'Close' : 'Cancel'}
        </button>
      </div>
    </div>
  )
}

// ── Optimization mode badge ───────────────────────────────────────────────────

function OptimizeBadge() {
  return (
    <span
      className="inline-flex items-center gap-1.5 h-6 px-2.5 rounded-full text-[11px] font-semibold border"
      style={{
        background: 'oklch(0.96 0.04 290)',
        borderColor: 'oklch(0.82 0.10 290)',
        color: 'oklch(0.42 0.18 290)',
      }}
    >
      <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
        <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z" />
      </svg>
      Profile Optimization Mode
    </span>
  )
}

// ── Main ProfileChat component ────────────────────────────────────────────────

const DISCLAIMER = 'The AI gathers this information to accurately reflect your true professional capabilities. Providing honest, precise, and complete answers is essential to achieve a genuine match with roles that truly suit you.'

export function ProfileChat({ intent, forceIntro = false }: { intent?: string; forceIntro?: boolean }) {
  const isOptimizeMode = intent === 'optimize_gaps'

  // Build the interview context from the authenticated user when available.
  // Falls back gracefully in DEV_MODE (user is null) — the backend will read
  // from its own USER_PROFILE constant in that case.
  const { user } = useAuth()

  // Resolve the display name using the same function that drives the avatar.
  // Only forward to the backend if the result is a real name (no @ sign, not
  // a bare email prefix).
  const _resolvedName = resolveDisplayName(
    user?.email,
    user?.user_metadata as Record<string, unknown> | null,
  )
  const _isRealName = Boolean(_resolvedName) && !_resolvedName.includes('@')

  const userContext: StartInterviewContext = {
    // Send the resolved full name so the backend can extract the exact first
    // name (e.g. "Jamie Smith" → "Jamie") without relying on email parsing.
    ...((_isRealName) ? { user_name: _resolvedName } : {}),
    // Forward the intent to the backend so it can tailor the opening prompt.
    ...(intent ? { intent } : {}),
  }

  const [session,      setSession]      = useState<InterviewSession | null>(null)
  const [input,        setInput]        = useState('')
  const [sending,      setSending]      = useState(false)
  const [starting,     setStarting]     = useState(false)
  const [restoring,    setRestoring]    = useState(false)
  const [uploadTarget, setUploadTarget] = useState<{ claim: string; docType: string } | null>(null)
  const [dragOver,     setDragOver]     = useState(false)
  const [uploading,    setUploading]    = useState(false)
  const bottomRef    = useRef<HTMLDivElement>(null)
  const textRef      = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragCounter  = useRef(0)

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => { scrollToBottom() }, [session?.messages.length, scrollToBottom])

  // ── On mount: restore existing session from localStorage ────────────────────
  useEffect(() => {
    // forceIntro=true means the caller wants the landing screen regardless of
    // existing session state — skip restoration entirely.
    if (forceIntro) return
    const savedId = localStorage.getItem(SESSION_STORAGE_KEY)
    if (!savedId) return

    setRestoring(true)
    ;(async () => {
      try {
        // Verify the session still exists, then generate the resume message
        await getInterviewSession(savedId)          // throws 404 if gone
        const resumed = await resumeInterviewSession(savedId)
        setSession(resumed)
      } catch {
        // Session expired or server restarted — clear stale key
        localStorage.removeItem(SESSION_STORAGE_KEY)
      } finally {
        setRestoring(false)
      }
    })()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleStart = useCallback(async () => {
    setStarting(true)
    try {
      // Pass auth-derived context so the backend can personalise the greeting.
      // The backend still reads its own authoritative USER_PROFILE data first;
      // userContext is only a fallback for when profile data is unavailable.
      const s = await startInterview(userContext)
      localStorage.setItem(SESSION_STORAGE_KEY, s.session_id)
      setSession(s)
    } catch {
      // fallback silent
    } finally {
      setStarting(false)
    }
  }, [])

  const handleReset = useCallback(() => {
    localStorage.removeItem(SESSION_STORAGE_KEY)
    setSession(null)
    setInput('')
    setDragOver(false)
    dragCounter.current = 0
  }, [])

  const handleSend = useCallback(async () => {
    if (!session || !input.trim() || sending) return
    const text = input.trim()
    setInput('')

    // Optimistic update
    setSession(prev => prev ? {
      ...prev,
      messages: [...prev.messages, { role: 'user', content: text, ts: new Date().toISOString() }],
    } : prev)
    setSending(true)

    try {
      const updated = await sendInterviewMessage(session.session_id, text)
      setSession(updated)
    } catch {
      setSession(prev => prev ? {
        ...prev,
        messages: [...prev.messages, {
          role: 'assistant',
          content: 'Sorry, something went wrong. Please try again.',
          ts: new Date().toISOString(),
        }],
      } : prev)
    } finally {
      setSending(false)
      textRef.current?.focus()
    }
  }, [session, input, sending])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleVerified = useCallback((_result: any) => {
    if (session) {
      getInterviewSession(session.session_id).then(s => setSession(s))
    }
  }, [session])

  // ── Inline upload (drag-and-drop / paperclip) ────────────────────────────────

  const handleInlineUpload = useCallback(async (file: File) => {
    if (!session) return
    const claim   = (session as any).doc_request?.for_claim ?? 'uploaded document'
    const ext     = file.name.split('.').pop()?.toLowerCase() ?? ''
    const docType = ext === 'pdf' ? 'pdf' : 'image'

    // Inject optimistic "uploading…" system message
    setSession(prev => prev ? {
      ...prev,
      messages: [...prev.messages, {
        role: 'system' as any,
        content: `📄 Uploading "${file.name}" for claim: ${claim}…`,
        ts: new Date().toISOString(),
      }],
    } : prev)

    setUploading(true)
    try {
      const res     = await uploadVerificationDocument(session.session_id, claim, docType, file)
      const updated = await getInterviewSession(session.session_id)
      const v       = res.verification
      const statusText =
        v.status === 'verified' ? '✓ Verified'        :
        v.status === 'partial'  ? '~ Partially verified' :
        v.status === 'failed'   ? '✗ Not verified'    : '⚠ Could not read'
      setSession(prev => {
        const base = updated
        // Replace the last system message with the result
        const msgs = [...(prev?.messages ?? base.messages).slice(0, -1), {
          role: 'system' as any,
          content: `📄 Document received — verifying your "${claim}"… ${statusText}. ${v.match_notes}`,
          ts: new Date().toISOString(),
        }]
        return { ...base, messages: msgs }
      })
    } catch {
      setSession(prev => prev ? {
        ...prev,
        messages: [...prev.messages.slice(0, -1), {
          role: 'system' as any,
          content: '📄 Upload failed. Please try again.',
          ts: new Date().toISOString(),
        }],
      } : prev)
    } finally {
      setUploading(false)
      // reset file input so the same file can be re-selected
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [session])

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current++
    if (dragCounter.current === 1) setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current--
    if (dragCounter.current === 0) setDragOver(false)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current = 0
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleInlineUpload(file)
  }, [handleInlineUpload])

  // ── Restoring existing session ───────────────────────────────────────────────
  if (restoring) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <SpinnerIcon s={28} />
        <p className="text-[13.5px] text-slate-500">Restoring your session…</p>
      </div>
    )
  }

  // ── Not started ──────────────────────────────────────────────────────────────
  if (!session) {
    if (isOptimizeMode) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-6 px-6">
          <div className="text-center max-w-md">
            <div className="text-4xl mb-3">🔍</div>
            <div className="flex justify-center mb-3">
              <OptimizeBadge />
            </div>
            <h2 className="text-[18px] font-bold text-slate-900 mb-2">Profile Strength Review</h2>
            <p className="text-[13.5px] text-slate-500 leading-relaxed">
              The AI will scan your existing profile, identify the traits or skills with the
              lowest confidence scores, acknowledge what it already knows about you, and then
              ask you to elaborate deeply — so those gaps get fully filled in.
            </p>
            <div className="mt-4 grid grid-cols-3 gap-3 text-center">
              {[
                { icon: '✦', label: 'Knows your profile', sub: 'Reads your captured data first' },
                { icon: '📉', label: 'Finds weak spots',   sub: 'Targets low-confidence claims' },
                { icon: '📈', label: 'Lifts your score',   sub: 'Deep answers raise confidence' },
              ].map(f => (
                <div key={f.label} className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-3">
                  <div className="text-xl mb-1">{f.icon}</div>
                  <p className="text-[11.5px] font-semibold text-slate-700">{f.label}</p>
                  <p className="text-[10.5px] text-slate-400 mt-0.5">{f.sub}</p>
                </div>
              ))}
            </div>
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-left">
              <p className="text-[11.5px] text-amber-800 leading-relaxed">
                <span className="font-semibold">ℹ️ Why accuracy matters: </span>
                {DISCLAIMER}
              </p>
            </div>
          </div>
          <button
            onClick={handleStart}
            disabled={starting}
            className="h-11 px-6 rounded-xl text-[14px] font-semibold text-white flex items-center gap-2 disabled:opacity-60"
            style={{ background: 'oklch(0.52 0.18 290)' }}
          >
            {starting ? <><SpinnerIcon s={16} /> Analysing…</> : '✦ Review My Profile Strengths'}
          </button>
        </div>
      )
    }

    return (
      <div className="flex flex-col items-center justify-center h-full gap-6 px-6">
        <div className="text-center max-w-md">
          <div className="text-4xl mb-4">🎙️</div>
          <h2 className="text-[18px] font-bold text-slate-900 mb-2">Profile Builder</h2>
          <p className="text-[13.5px] text-slate-500 leading-relaxed">
            Build a verified, evidence-backed professional profile through conversation.
            Every claim is scored for confidence — and you can upload documents to verify them.
          </p>
          <div className="mt-4 grid grid-cols-3 gap-3 text-center">
            {[
              { icon: '💬', label: 'Conversational', sub: 'Talk freely, we extract the data' },
              { icon: '🎯', label: 'Evidence-first', sub: 'Every claim has a confidence score' },
              { icon: '📄', label: 'Document verified', sub: 'Upload proof to reach 100%' },
            ].map(f => (
              <div key={f.label} className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-3">
                <div className="text-xl mb-1">{f.icon}</div>
                <p className="text-[11.5px] font-semibold text-slate-700">{f.label}</p>
                <p className="text-[10.5px] text-slate-400 mt-0.5">{f.sub}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-left">
            <p className="text-[11.5px] text-amber-800 leading-relaxed">
              <span className="font-semibold">ℹ️ Why accuracy matters: </span>
              {DISCLAIMER}
            </p>
          </div>
        </div>
        <button
          onClick={handleStart}
          disabled={starting}
          className="h-11 px-6 rounded-xl text-[14px] font-semibold text-white flex items-center gap-2 disabled:opacity-60"
          style={{ background: TOKENS.color.primary }}
        >
          {starting ? <><SpinnerIcon s={16} /> Starting…</> : '✦ Start Profile Interview'}
        </button>
      </div>
    )
  }

  // ── Active session ─────────────────────────────────────────────────────────
  return (
    <div className="flex h-full overflow-hidden">
      {/* Chat pane */}
      <div
        className="relative flex flex-col flex-1 min-w-0 border-r border-slate-100"
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        {/* Chat header bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-100 bg-white flex-shrink-0 gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <p className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide shrink-0">
              Profile Interview
            </p>
            {isOptimizeMode && <OptimizeBadge />}
          </div>
          <button
            onClick={handleReset}
            title="Clear this session and start a new interview"
            className="h-7 px-3 rounded-full text-[11.5px] text-rose-500 hover:text-rose-700 hover:bg-rose-50 border border-transparent hover:border-rose-200 transition shrink-0"
          >
            ↺ Reset Interview
          </button>
        </div>

        {/* Drag-over overlay */}
        {dragOver && (
          <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 rounded-none pointer-events-none"
            style={{ background: 'rgba(109,40,217,0.08)', border: '2px dashed #7c3aed' }}
          >
            <PaperclipIcon s={32} />
            <p className="text-[15px] font-semibold text-violet-700">Drop file here to upload</p>
            <p className="text-[12px] text-violet-500">PDF · PNG · JPG · JPEG</p>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {session.messages.map((msg, idx) => {
            const role = (msg as any).role as string
            // System messages render as centered informational pills
            if (role === 'system') {
              return (
                <div key={idx} className="flex justify-center">
                  <span className="inline-flex items-center gap-1.5 h-7 px-3 rounded-full bg-slate-100 text-slate-500 text-[11.5px] border border-slate-200">
                    {uploading && idx === session.messages.length - 1
                      ? <><SpinnerIcon s={12} /> {msg.content}</>
                      : msg.content
                    }
                  </span>
                </div>
              )
            }
            return (
            <div key={idx} className={`flex ${role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {role === 'assistant' && (
                <div
                  className="w-7 h-7 rounded-full text-white text-[11px] font-bold flex items-center justify-center mr-2 mt-0.5 flex-shrink-0"
                  style={{ background: TOKENS.color.primary }}
                  title="Adam — Profile Specialist"
                >
                  A
                </div>
              )}
              <div
                className={`max-w-[78%] rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap ${
                  role === 'user'
                    ? 'text-white rounded-tr-sm'
                    : 'bg-white border border-slate-100 text-slate-800 rounded-tl-sm'
                }`}
                style={role === 'user' ? { background: TOKENS.color.primary } : undefined}
              >
                {role === 'assistant' ? sanitizeText(msg.content) : msg.content}
              </div>
            </div>
            )
          })}

          {/* Typing indicator */}
          {sending && (
            <div className="flex justify-start">
              <div
                className="w-7 h-7 rounded-full text-white text-[11px] font-bold flex items-center justify-center mr-2 mt-0.5 flex-shrink-0"
                style={{ background: TOKENS.color.primary }}
                title="Adam — Profile Specialist"
              >
                A
              </div>
              <div className="bg-white border border-slate-100 rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1">
                {[0, 1, 2].map(i => (
                  <span
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-slate-300"
                    style={{ animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite` }}
                  />
                ))}
                <style>{`@keyframes bounce { 0%,80%,100% { transform: translateY(0) } 40% { transform: translateY(-6px) } }`}</style>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div className="p-3 border-t border-slate-100 flex items-end gap-2">
          {/* Paperclip / attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            title="Attach document"
            className="w-9 h-9 rounded-xl flex items-center justify-center text-slate-400 hover:text-violet-600 hover:bg-violet-50 transition flex-shrink-0 disabled:opacity-40"
          >
            <PaperclipIcon s={16} />
          </button>
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg"
            className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) handleInlineUpload(f) }}
          />
          <textarea
            ref={textRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your answer… (Shift+Enter for new line)"
            rows={2}
            className="flex-1 resize-none rounded-xl border border-slate-200 px-3 py-2.5 text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-slate-400 bg-white"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || sending}
            className="w-9 h-9 rounded-xl flex items-center justify-center text-white transition disabled:opacity-40 flex-shrink-0"
            style={{ background: TOKENS.color.primary }}
          >
            <SendIcon s={15} />
          </button>
        </div>
      </div>

      {/* Draft profile sidebar */}
      <div className="w-72 flex-shrink-0 overflow-y-auto bg-slate-50">
        <DraftPanel
          session={session}
          onUploadRequest={(claim, docType) => setUploadTarget({ claim, docType })}
        />
      </div>

      {/* Upload modal */}
      {uploadTarget && session && (
        <UploadZone
          sessionId={session.session_id}
          claim={uploadTarget.claim}
          docType={uploadTarget.docType}
          onVerified={handleVerified}
          onClose={() => setUploadTarget(null)}
        />
      )}
    </div>
  )
}
