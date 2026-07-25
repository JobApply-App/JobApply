'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { usePathname } from 'next/navigation'
import { useChat }   from '@/contexts/ChatContext'
import type { ChatMessage } from '@/contexts/ChatContext'
import { useAuth }   from '@/contexts/AuthContext'
import { TOKENS }    from '@/lib/tokens'
import { ArielChat } from '@/components/ArielChat'
import { consumeArielWelcome } from '@/lib/onboardingFlags'

// Routes that belong to the onboarding flow — Ariel must never render there.
const ONBOARDING_ROUTES = ['/onboarding', '/profile-builder']

/**
 * Strict onboarding-route check: consults BOTH the React pathname (usePathname)
 * and the live browser URL. During soft-routing transitions the two can be
 * momentarily out of sync — usePathname updates on React's schedule, while
 * window.location changes immediately — which let Ariel flash for a frame.
 * She is hidden if EITHER source says we're on an onboarding route.
 */
function isOnOnboardingRoute(reactPathname: string | null): boolean {
  const browserPathname = typeof window !== 'undefined' ? window.location.pathname : ''
  return ONBOARDING_ROUTES.some(r =>
    (reactPathname ?? '').startsWith(r) || browserPathname.startsWith(r)
  )
}

// ── Public-chat attachment support ────────────────────────────────────────────

interface FileAttachment {
  base64:    string   // raw base64 without the "data:…;base64," prefix
  mediaType: string
  name:      string
}

const MAX_ATTACHMENTS   = 10
const MAX_FILE_SIZE_MB  = 5
const MAX_TOTAL_SIZE_MB = 20

const approxBytesFromBase64 = (b64: string) => Math.floor(b64.length * 0.75)

// ── Session-ID helpers (public/anonymous mode only) ───────────────────────────

const PUBLIC_SESSION_KEY = 'jobapply_public_session_id'

function getOrCreateSessionId(): string {
  if (typeof window === 'undefined') return ''
  try {
    const stored = localStorage.getItem(PUBLIC_SESSION_KEY)
    if (stored && /^[0-9a-f-]{36}$/i.test(stored)) return stored
    const id = crypto.randomUUID()
    localStorage.setItem(PUBLIC_SESSION_KEY, id)
    return id
  } catch {
    return crypto.randomUUID()
  }
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function CloseIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width={13} height={13} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  )
}

function PaperclipIcon({ s = 15 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.41 17.41a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg width={12} height={12} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function SpinnerIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'chat-spin 0.8s linear infinite', flexShrink: 0 }}>
      <style>{`@keyframes chat-spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

// ── Markdown-lite renderer ────────────────────────────────────────────────────

function renderInline(text: string, key?: number): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/)
  return (
    <span key={key}>
      {parts.map((p, i) =>
        p.startsWith('**') && p.endsWith('**')
          ? <strong key={i} className="font-semibold text-slate-900">{p.slice(2, -2)}</strong>
          : <span key={i}>{p}</span>
      )}
    </span>
  )
}

function renderMarkdown(text: string): React.ReactNode {
  const paragraphs = text.split('\n\n').filter(Boolean)
  return paragraphs.map((para, pi) => {
    const lines = para.split('\n')
    if (lines.every(l => l.startsWith('- ') || l.startsWith('* ') || l.startsWith('• '))) {
      return (
        <ul key={pi} className="space-y-1 mb-2">
          {lines.map((l, li) => (
            <li key={li} className="flex items-start gap-1.5">
              <span className="mt-[6px] shrink-0 w-[4px] h-[4px] rounded-full bg-slate-400" />
              <span className="flex-1">{renderInline(l.replace(/^[-*•]\s+/, ''))}</span>
            </li>
          ))}
        </ul>
      )
    }
    return <p key={pi} className="mb-2 last:mb-0">{lines.map(renderInline)}</p>
  })
}

// ── Tool-call Action Card (authenticated mode only) ───────────────────────────

const TOOL_LABELS: Record<string, string> = {
  tailor_resume_for_job: 'Resume Tailoring Triggered',
}

interface ActionCardProps {
  toolName:  string
  toolArgs:  Record<string, unknown>
  onConfirm: () => void
  onDismiss: () => void
}

function ActionCard({ toolName, toolArgs, onConfirm, onDismiss }: ActionCardProps) {
  const [dismissed, setDismissed] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  if (dismissed) return null

  const heading  = TOOL_LABELS[toolName] ?? toolName
  const jobTitle = typeof toolArgs.job_title === 'string' ? toolArgs.job_title : ''
  const company  = typeof toolArgs.company   === 'string' ? toolArgs.company   : ''
  const skills   = Array.isArray(toolArgs.focus_skills)
    ? (toolArgs.focus_skills as unknown[]).filter((s): s is string => typeof s === 'string')
    : []

  return (
    <div className="bg-white border border-slate-100 rounded-xl shadow-sm overflow-hidden">
      <div className="h-0.5 w-full" style={{ background: TOKENS.color.primary }} />
      <div className="px-4 py-3.5 space-y-3">
        <div className="flex items-center gap-2">
          <span
            className="inline-flex items-center justify-center w-6 h-6 rounded-md text-white text-[11px] font-bold shrink-0"
            style={{ background: TOKENS.color.primary }}
          >
            AI
          </span>
          <p className="text-[12.5px] font-semibold text-slate-900 leading-tight">{heading}</p>
        </div>
        {(jobTitle || company) && (
          <div className="text-[12px] text-slate-600">
            <span className="font-medium text-slate-800">{jobTitle}</span>
            {company && <span className="text-slate-400"> &middot; {company}</span>}
          </div>
        )}
        {skills.length > 0 && (
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">Focus skills</p>
            <div className="flex flex-wrap gap-1.5">
              {skills.map((s, i) => (
                <span key={i} className="inline-flex items-center px-2 py-0.5 rounded-md bg-slate-50 border border-slate-200 text-[11px] font-medium text-slate-700">
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}
        {confirmed ? (
          <p className="text-[11.5px] font-medium text-teal-700 flex items-center gap-1.5">
            <CheckIcon /> Tailoring started - check the Matches feed.
          </p>
        ) : (
          <div className="flex items-center gap-2 pt-0.5">
            <button
              onClick={() => { setConfirmed(true); onConfirm() }}
              className="flex-1 h-8 rounded-lg text-white text-[11.5px] font-semibold tracking-wide transition active:scale-[0.97]"
              style={{ background: TOKENS.color.primary }}
            >
              Confirm &amp; Generate
            </button>
            <button
              onClick={() => { setDismissed(true); onDismiss() }}
              className="h-8 px-3 rounded-lg text-[11.5px] font-medium text-slate-500 hover:text-slate-800 hover:bg-slate-50 transition"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Message bubble ────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message:       ChatMessage
  onToolConfirm: (toolName: string, toolArgs: Record<string, unknown>) => void
  onToolDismiss: () => void
}

function MessageBubble({ message, onToolConfirm, onToolDismiss }: MessageBubbleProps) {
  const { role, content, isToolCall, toolName, toolArgs } = message

  if (isToolCall && toolName && toolArgs) {
    return (
      <ActionCard
        toolName={toolName}
        toolArgs={toolArgs}
        onConfirm={() => onToolConfirm(toolName, toolArgs)}
        onDismiss={onToolDismiss}
      />
    )
  }

  if (role === 'system') {
    return (
      <div className="flex justify-center">
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-100 text-slate-500 text-[11px] border border-slate-200">
          {content}
        </span>
      </div>
    )
  }

  const isUser = role === 'user'
  if (isUser && content.startsWith("I'm looking at ")) return null

  return (
    <div className={`flex items-end ${isUser ? 'justify-end' : 'justify-start'}`}>
      {/* No per-bubble avatar — identity is established in the panel header */}
      <div
        dir="auto"
        className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 text-[12.5px] leading-relaxed ${
          isUser
            ? 'rounded-br-sm text-white'
            : 'rounded-bl-sm bg-slate-50 border border-slate-100 text-slate-700'
        }`}
        style={isUser ? { background: TOKENS.color.primary } : undefined}
      >
        {isUser ? content : renderMarkdown(content)}
      </div>
    </div>
  )
}

// ── Typing indicator ──────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex items-end justify-start">
      <div className="bg-slate-50 border border-slate-100 rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-1">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-slate-300"
            style={{ animation: `chat-bounce 1.2s ease-in-out ${i * 0.2}s infinite` }}
          />
        ))}
        <style>{`
          @keyframes chat-bounce {
            0%, 80%, 100% { transform: translateY(0); }
            40%           { transform: translateY(-5px); }
          }
        `}</style>
      </div>
    </div>
  )
}

// ── Context pill (authenticated mode) ────────────────────────────────────────

function ContextPill({ topic }: { topic: string }) {
  return (
    <div className="px-4 py-2.5 border-b border-slate-800/40">
      <div
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px]"
        style={{ background: 'rgba(13,148,136,0.18)', border: '1px solid rgba(13,148,136,0.35)' }}
      >
        <span style={{ color: '#5eead4' }}>AI</span>
        <span style={{ color: '#99f6e4' }} className="font-medium truncate">{topic}</span>
      </div>
    </div>
  )
}

// ── Eliya colour tokens (indigo "Support" theme) ──────────────────────────────
const ELIYA = {
  primary:     '#4F46E5',   // indigo-600
  primaryHover:'#4338CA',   // indigo-700
  primarySoft: '#EEF2FF',   // indigo-50
  ring:        'rgba(79,70,229,0.20)',
  border:      '#C7D2FE',   // indigo-200
}

const WELCOME_SUGGESTIONS = [
  { icon: '🚀', label: 'What does JobApply do?',    prompt: 'What does JobApply do and how do I get started?' },
  { icon: '🔐', label: 'Help me sign up',            prompt: 'I want to create an account — walk me through signing up.' },
  { icon: '📄', label: 'How does CV tailoring work?', prompt: 'How does the CV tailoring feature work?' },
  { icon: '🐛', label: "Something's not working",    prompt: "Something on the site isn't working for me. Can you help?" },
]

// ── Public (Eliya) chat panel ─────────────────────────────────────────────────
//
// Used when the visitor is NOT authenticated.  Maintains its own local message
// state, calls /api/chat/public, and tracks a persistent anonymous session_id.

function PublicChatPanel({ onClose }: { onClose: () => void }) {
  const [messages,    setMessages]    = useState<ChatMessage[]>([])
  const [draft,       setDraft]       = useState('')
  const [thinking,    setThinking]    = useState(false)
  const [sessionId,   setSessionId]   = useState('')
  const [attachments, setAttachments] = useState<FileAttachment[]>([])
  const [attachError, setAttachError] = useState<string | null>(null)
  const bottomRef   = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileRef     = useRef<HTMLInputElement>(null)
  const attachErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Resolve / create the anonymous session ID once on mount (client only)
  useEffect(() => {
    setSessionId(getOrCreateSessionId())
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, thinking])

  // ── Attachment handling (mirrors ArielChat's attachFiles) ──────────────────
  const attachFiles = useCallback((incoming: File[]) => {
    if (!incoming.length) return

    const deduped = incoming.filter((f, i) =>
      !attachments.some(a => a.name === f.name) &&
      !incoming.slice(0, i).some(earlier => earlier.name === f.name && earlier.size === f.size)
    )
    if (!deduped.length) return

    const perFileLimit = MAX_FILE_SIZE_MB  * 1024 * 1024
    const totalLimit   = MAX_TOTAL_SIZE_MB * 1024 * 1024

    let runningCount = attachments.length
    let runningBytes = attachments.reduce((sum, a) => sum + approxBytesFromBase64(a.base64), 0)

    const accepted: File[] = []
    let rejectedOversize = 0
    let rejectedCapacity = 0

    for (const file of deduped) {
      if (file.size > perFileLimit) { rejectedOversize++; continue }
      if (runningCount + 1 > MAX_ATTACHMENTS)    { rejectedCapacity++; continue }
      if (runningBytes + file.size > totalLimit) { rejectedCapacity++; continue }
      accepted.push(file)
      runningCount += 1
      runningBytes += file.size
    }

    if (rejectedOversize || rejectedCapacity) {
      const parts: string[] = []
      if (rejectedOversize) parts.push(`${rejectedOversize} over ${MAX_FILE_SIZE_MB}MB each`)
      if (rejectedCapacity) parts.push(`limit is ${MAX_ATTACHMENTS} files / ${MAX_TOTAL_SIZE_MB}MB total`)
      const skipped = rejectedOversize + rejectedCapacity
      if (attachErrorTimerRef.current) clearTimeout(attachErrorTimerRef.current)
      setAttachError(`${skipped} file${skipped > 1 ? 's' : ''} skipped — ${parts.join(', ')}.`)
      attachErrorTimerRef.current = setTimeout(() => setAttachError(null), 4000)
    }

    if (!accepted.length) return

    accepted.forEach(file => {
      const reader = new FileReader()
      reader.onload = ev => {
        const dataUrl = ev.target?.result as string
        setAttachments(cur => {
          if (cur.length >= MAX_ATTACHMENTS) return cur
          return [...cur, {
            base64:    dataUrl.split(',')[1] ?? '',
            mediaType: file.type,
            name:      file.name,
          }]
        })
      }
      reader.readAsDataURL(file)
    })
  }, [attachments])

  useEffect(() => {
    return () => { if (attachErrorTimerRef.current) clearTimeout(attachErrorTimerRef.current) }
  }, [])

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    attachFiles(files)
  }, [attachFiles])

  const handleSend = useCallback(async (override?: string) => {
    const text = (override ?? draft).trim()
    if ((!text && !attachments.length) || thinking || !sessionId) return

    const userMsg: ChatMessage = { role: 'user', content: text || 'Please look at the attached files.', ts: Date.now() }
    // Snapshot current messages for history before state update
    const historySnapshot = messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(({ role, content }) => ({ role: role as 'user' | 'assistant', content }))

    const capturedAttachments = attachments
    setAttachments([])
    setMessages(prev => [...prev, userMsg])
    setDraft('')
    setThinking(true)

    const assistantTs = Date.now()
    let streamStarted = false
    let accumulated   = ''

    try {
      const res = await fetch('/api/chat/public', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          session_id:  sessionId,
          message:     userMsg.content,
          history:     historySnapshot,
          attachments: capturedAttachments.length
            ? capturedAttachments.map(a => ({ base64: a.base64, mediaType: a.mediaType, name: a.name }))
            : undefined,
        }),
      })

      if (res.status === 429) {
        // Rate limited — show a polite "busy" notice instead of a raw error.
        setMessages(prev => [...prev, {
          role:    'assistant',
          content: "I'm helping a lot of visitors right now — please give me a moment and try again shortly. 🙏",
          ts:      Date.now(),
        }])
        return
      }

      if (!res.ok || !res.body) {
        // Non-streaming error response (FastAPI uses `detail`, Next uses `error`)
        const errData = await res.json().catch(() => ({})) as { error?: string; detail?: string }
        throw new Error(errData.error ?? errData.detail ?? `HTTP ${res.status}`)
      }

      const reader     = res.body.getReader()
      const decoder    = new TextDecoder()
      let   lineBuffer = ''

      outer: while (true) {
        const { done, value } = await reader.read()
        if (done) break

        lineBuffer += decoder.decode(value, { stream: true })
        const events = lineBuffer.split('\n\n')
        lineBuffer   = events.pop() ?? ''

        for (const event of events) {
          for (const line of event.split('\n')) {
            if (!line.startsWith('data:')) continue
            const payload = line.slice(5).trim()
            if (payload === '[DONE]') break outer

            let parsed: { chunk?: string; error?: string }
            try { parsed = JSON.parse(payload) as typeof parsed }
            catch { continue }

            if (parsed.error) throw new Error(parsed.error)
            if (!parsed.chunk) continue

            accumulated += parsed.chunk

            if (!streamStarted) {
              streamStarted = true
              setThinking(false)
              setMessages(prev => [
                ...prev,
                { role: 'assistant', content: accumulated, ts: assistantTs },
              ])
            } else {
              setMessages(prev => {
                const next = [...prev]
                next[next.length - 1] = { ...next[next.length - 1], content: accumulated }
                return next
              })
            }
          }
        }
      }

      if (!streamStarted) {
        setMessages(prev => [...prev, {
          role: 'assistant', content: '_(No response received.)_', ts: assistantTs,
        }])
      }

    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      const msg = err instanceof Error ? err.message : 'Something went wrong. Please try again.'
      setMessages(prev => [...prev, { role: 'assistant', content: msg, ts: Date.now() }])
    } finally {
      setThinking(false)
    }
  }, [draft, thinking, sessionId, messages, attachments])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleDraftChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDraft(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`
  }

  return (
    <>
      {/* Header — indigo Support theme */}
      <div
        className="flex-shrink-0 flex items-center justify-between px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))]"
        style={{ background: '#1e1b4b' }}
      >
        <div className="flex items-center gap-2.5">
          <div
            className="w-7 h-7 rounded-2xl flex items-center justify-center text-[11px] font-bold text-white"
            style={{ background: ELIYA.primary }}
          >
            E
          </div>
          <div>
            <p className="text-[13px] font-semibold text-white leading-tight">Eliya</p>
            <p className="text-[10.5px] leading-tight" style={{ color: '#a5b4fc' }}>Support &amp; Onboarding</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button
              onClick={() => setMessages([])}
              title="Clear conversation"
              className="w-11 h-11 sm:w-7 sm:h-7 flex items-center justify-center rounded-lg transition-colors active:bg-indigo-500/25 sm:hover:bg-indigo-500/15"
              style={{ color: '#6366f1' }}
            >
              <TrashIcon />
            </button>
          )}
          <button
            onClick={onClose}
            title="Close"
            aria-label="Close Eliya"
            // Persistent bg-white/10 chip (not hover/active-only) so the
            // close control reads as a clear, tappable affordance on touch
            // devices, where :hover never fires and the icon alone was low-
            // contrast against the dark header.
            className="w-11 h-11 sm:w-7 sm:h-7 flex items-center justify-center rounded-full bg-white/10 text-white transition-colors active:bg-indigo-500/30 sm:hover:bg-white/20"
          >
            <CloseIcon />
          </button>
        </div>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto bg-white px-4 py-4 space-y-3 min-h-0">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center pb-4">
            <div
              className="w-12 h-12 rounded-2xl flex items-center justify-center text-white text-lg font-bold"
              style={{ background: ELIYA.primary }}
            >
              E
            </div>
            <p dir="ltr" className="text-[13px] font-semibold text-slate-700">Hi, I&apos;m Eliya</p>
            <p dir="ltr" className="text-[12px] text-slate-400 leading-relaxed max-w-[240px]">
              Ask me anything about JobApply and I&apos;ll help you get started.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-1.5 max-w-[280px] pt-1">
              {WELCOME_SUGGESTIONS.map(s => (
                <button
                  key={s.label}
                  dir="ltr"
                  onClick={() => handleSend(s.prompt)}
                  className="inline-flex items-center gap-1.5 pl-2 pr-2.5 min-h-[44px] sm:py-1.5 sm:min-h-0 rounded-full border text-[12px] font-medium transition-colors"
                  style={{ borderColor: ELIYA.border, background: ELIYA.primarySoft, color: ELIYA.primaryHover }}
                >
                  <span aria-hidden="true">{s.icon}</span>
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            onToolConfirm={() => {}}
            onToolDismiss={() => {}}
          />
        ))}

        {thinking && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      {/* Input bar — indigo theme */}
      <div
        className="flex-shrink-0 border-t bg-white px-3 pt-2 pb-[max(0.625rem,env(safe-area-inset-bottom))] space-y-1.5"
        style={{ borderColor: ELIYA.border }}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); attachFiles(Array.from(e.dataTransfer.files)) }}
      >
        {/* Hidden file input */}
        <input
          ref={fileRef}
          type="file"
          accept="image/*,.pdf"
          multiple
          className="hidden"
          onChange={handleFileChange}
        />

        {/* Attachment pills */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 p-1 overflow-y-auto max-h-24">
            {attachments.map((a, i) => {
              const dot   = a.name.lastIndexOf('.')
              const base  = dot > 0 ? a.name.slice(0, dot) : a.name
              const ext   = dot > 0 ? a.name.slice(dot)    : ''
              const label = base.length > 10 ? `${base.slice(0, 8)}…${ext}` : a.name
              return (
                <div
                  key={i}
                  className="flex items-center gap-1.5 text-xs px-2 py-1 rounded text-white"
                  style={{ background: ELIYA.primary }}
                >
                  <span className="max-w-[90px] truncate leading-none" title={a.name}>{label}</span>
                  <button
                    type="button"
                    onClick={() => setAttachments(prev => prev.filter((_, idx) => idx !== i))}
                    className="shrink-0 opacity-70 hover:opacity-100 focus-visible:opacity-100 transition leading-none ml-0.5"
                    title="Remove"
                    aria-label={`Remove ${a.name}`}
                  >✕</button>
                </div>
              )
            })}
          </div>
        )}

        {/* Attachment error notice — auto-dismisses after 4s */}
        {attachError && (
          <div role="status" className="text-[11px] text-ja-danger bg-ja-dangerSubtle rounded-lg px-2.5 py-1.5">
            {attachError}
          </div>
        )}

        <div className="flex items-end gap-2">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            title={`Attach images or PDFs (screenshots help!) — max ${MAX_ATTACHMENTS} files, up to ${MAX_FILE_SIZE_MB}MB each, ${MAX_TOTAL_SIZE_MB}MB total`}
            aria-label="Attach files"
            disabled={thinking || attachments.length >= MAX_ATTACHMENTS}
            className="shrink-0 w-11 h-11 sm:w-9 sm:h-9 flex items-center justify-center rounded-xl text-slate-400 active:bg-slate-200 sm:hover:text-slate-700 sm:hover:bg-slate-100 focus-visible:text-slate-700 focus-visible:bg-slate-100 transition disabled:opacity-40"
          >
            <PaperclipIcon />
          </button>

          <textarea
            ref={textareaRef}
            value={draft}
            onChange={handleDraftChange}
            onKeyDown={handleKeyDown}
            placeholder="Ask Eliya anything…"
            dir="auto"
            rows={1}
            autoFocus
            disabled={thinking}
            className="flex-1 resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none transition disabled:opacity-50 min-h-[44px] max-h-[120px]"
            style={{ lineHeight: '1.5' }}
            onFocus={e => { e.currentTarget.style.borderColor = ELIYA.primary; e.currentTarget.style.boxShadow = `0 0 0 2px ${ELIYA.ring}` }}
            onBlur={e =>  { e.currentTarget.style.borderColor = ''; e.currentTarget.style.boxShadow = '' }}
          />
          <button
            onClick={() => handleSend()}
            disabled={(!draft.trim() && !attachments.length) || thinking}
            title="Send (Enter)"
            aria-label="Send message"
            className="shrink-0 w-11 h-11 sm:w-9 sm:h-9 rounded-xl flex items-center justify-center text-white transition active:scale-95 disabled:opacity-35 disabled:pointer-events-none"
            style={{ background: ELIYA.primary }}
          >
            {thinking ? <SpinnerIcon /> : <SendIcon />}
          </button>
        </div>
      </div>
    </>
  )
}

// AuthChatPanel replaced by ArielChat (imported above)

// ── Overlay shell helper ──────────────────────────────────────────────────────

// User-resizable on desktop only (sm breakpoint, 640px+) — mobile keeps the
// fixed full-width/full-height sheet since drag-resize handles don't work well
// with touch and there's no room to grow anyway.
const _DEFAULT_SIZE = { width: 380, height: 520 }
const _MIN_WIDTH  = 320
const _MIN_HEIGHT = 360

function _useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 640px)')
    const update = () => setIsDesktop(mq.matches)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])
  return isDesktop
}

// Max dimensions mirrored from the inline style below (`min(720px, ...)` /
// `min(800px, ...)`) so the drag handler can clamp without reading layout.
const _MAX_WIDTH  = 720
const _MAX_HEIGHT = 800

// ── Top-left resize handle ────────────────────────────────────────────────
//
// The panel is anchored to the viewport's bottom-right corner (`fixed
// bottom-0 right-0`), so growing width/height while that anchor stays fixed
// naturally expands the panel toward the top-left — no separate
// repositioning of the container is needed, only the size state changes.
//
// Visual placement: the panel corner itself is clipped by `rounded-2xl`
// (16px radius), so a grip drawn flush at (0,0) would render inside that
// clipped-away sliver and be invisible — hence the 6px inset (`top-1.5
// left-1.5`), which keeps the whole chip inside the visible rounded area.
// The 6px inset also keeps it clear of both header layouts' avatar, which
// starts at least 12px from each edge in every panel that uses this shell.
function TopLeftResizeHandle({
  size,
  setSize,
  variant = 'onLight',
  onResizeStart,
}: {
  size:          { width: number; height: number }
  setSize:       React.Dispatch<React.SetStateAction<{ width: number; height: number }>>
  variant?:      'onLight' | 'onDark'
  onResizeStart: () => void
}) {
  const [hover, setHover]     = useState(false)
  const [dragging, setDragging] = useState(false)
  const dragRef = useRef<{ startX: number; startY: number; startW: number; startH: number } | null>(null)

  const onPointerMove = useCallback((e: PointerEvent) => {
    const drag = dragRef.current
    if (!drag) return
    const deltaX = e.clientX - drag.startX
    const deltaY = e.clientY - drag.startY
    // Dragging toward the top-left (negative delta) grows the panel;
    // dragging back toward the bottom-right shrinks it.
    const nextWidth  = Math.min(_MAX_WIDTH,  Math.max(_MIN_WIDTH,  drag.startW - deltaX))
    const nextHeight = Math.min(_MAX_HEIGHT, Math.max(_MIN_HEIGHT, drag.startH - deltaY))
    setSize({ width: nextWidth, height: nextHeight })
  }, [setSize])

  const onPointerUp = useCallback((e: PointerEvent) => {
    dragRef.current = null
    setDragging(false)
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
    ;(e.target as Element | null)?.releasePointerCapture?.(e.pointerId)
  }, [onPointerMove])

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    setDragging(true)
    onResizeStart()
    dragRef.current = { startX: e.clientX, startY: e.clientY, startW: size.width, startH: size.height }
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
  }, [size, onPointerMove, onPointerUp, onResizeStart])

  useEffect(() => {
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
    }
  }, [onPointerMove, onPointerUp])

  const isDark   = variant === 'onDark'
  const active   = hover || dragging
  const iconColor = isDark ? 'rgba(255,255,255,0.92)' : 'rgba(51,65,85,0.85)'   // slate-700-ish
  const chipBg    = active
    ? (isDark ? 'rgba(255,255,255,0.22)' : 'rgba(15,23,42,0.10)')
    : (isDark ? 'rgba(255,255,255,0.10)' : 'rgba(15,23,42,0.05)')

  return (
    <div
      onPointerDown={onPointerDown}
      onPointerEnter={() => setHover(true)}
      onPointerLeave={() => setHover(false)}
      title="Drag to resize"
      aria-label="Resize chat window"
      role="separator"
      className="absolute top-1.5 left-1.5 z-20 w-[18px] h-[18px] rounded-full flex items-center justify-center touch-none transition-colors duration-150"
      style={{ background: chipBg, cursor: 'nwse-resize' }}
    >
      {/* Diagonal grip — two parallel strokes on the NW↔SE axis, matching the
          nwse-resize cursor direction (identical convention used for both
          top-left and bottom-right resize corners). */}
      <svg width={9} height={9} viewBox="0 0 9 9" className="pointer-events-none">
        <line x1="1.5" y1="7.5" x2="7.5" y2="1.5" stroke={iconColor} strokeWidth="1.3" strokeLinecap="round" />
        <line x1="1.5" y1="4"   x2="4"   y2="1.5" stroke={iconColor} strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    </div>
  )
}

function OverlayShell({
  isOpen,
  onBackdropClick,
  offsetRight = '1.5rem',
  ariaLabel,
  shadowColor = 'rgba(15,23,42,0.20)',
  handleVariant = 'onLight',
  children,
}: {
  isOpen:          boolean
  onBackdropClick: () => void
  offsetRight?:    string
  ariaLabel:       string
  shadowColor?:    string
  handleVariant?:  'onLight' | 'onDark'
  children:        React.ReactNode
}) {
  const isDesktop  = _useIsDesktop()
  const [size, setSize] = useState(_DEFAULT_SIZE)
  // Desktop starts at a viewport-relative `sm:h-[85vh]` (Tailwind class,
  // below) rather than a hardcoded pixel default — `userResized` tracks
  // whether the user has actually dragged the corner handle at least once;
  // until then the class governs height, so the panel scales sensibly across
  // different desktop monitor sizes instead of always opening at a fixed px.
  const [userResized, setUserResized] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  // Sync `size.height` to the panel's actual rendered height (driven by the
  // `sm:h-[85vh]` class up to this point) before handing control to the
  // inline-style/state-driven path — otherwise the drag math would start
  // from the stale `_DEFAULT_SIZE.height` (520px) and the panel would jump
  // to that height the instant the user starts dragging.
  const handleResizeStart = useCallback(() => {
    const rect = panelRef.current?.getBoundingClientRect()
    if (rect) setSize(prev => ({ ...prev, height: rect.height }))
    setUserResized(true)
  }, [])

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/55 backdrop-blur-[4px] sm:hidden"
          onClick={onBackdropClick}
        />
      )}
      {/* Ariel overlay — Meridian V2 §6.1 names this specifically as light-glass */}
      <div
        ref={panelRef}
        role="dialog"
        aria-label={ariaLabel}
        aria-modal="true"
        className="fixed bottom-0 right-0 z-50 flex flex-col w-full h-[100vh] h-[100dvh] rounded-none sm:h-[85vh] sm:bottom-6 sm:rounded-2xl overflow-hidden transition-all duration-[250ms] ease-out bg-white/85 backdrop-blur-xl border border-white/60"
        style={{
          // Mobile: `h-[100dvh]` above (with `100vh` as the pre-dvh-support
          // fallback, via cascade — not settable in a single inline value)
          // tracks the real visible viewport as mobile browser chrome and
          // the on-screen keyboard show/hide, so the sheet is always a true
          // full-screen sheet and never leaves a gap. Desktop defaults to
          // the `sm:h-[85vh]` class (viewport-relative) until the user drags
          // the resize handle, at which point this inline style takes over
          // and drives height from `size` state instead.
          height:        isOpen ? (isDesktop && userResized ? `${size.height}px` : undefined) : '0px',
          width:         isDesktop ? `${size.width}px` : undefined,
          minWidth:      isDesktop ? `${_MIN_WIDTH}px` : undefined,
          minHeight:     isDesktop ? `${_MIN_HEIGHT}px` : undefined,
          maxWidth:      isDesktop ? 'min(720px, calc(100vw - 48px))' : undefined,
          maxHeight:     isDesktop ? 'min(800px, calc(100vh - 120px))' : undefined,
          opacity:       isOpen ? 1 : 0,
          pointerEvents: isOpen ? 'auto' : 'none',
          transform:     isOpen ? 'translateY(0) scale(1)' : 'translateY(16px) scale(0.97)',
          boxShadow:     `0 24px 64px ${shadowColor}, 0 4px 16px rgba(15,23,42,0.10)`,
          // Desktop only: floating offset from the right edge. Previously
          // applied unconditionally, which fought the mobile `w-full` width
          // (inline style always wins over the `right-0` Tailwind class) and
          // pushed the sheet's left edge off-screen on mobile.
          right:         isDesktop ? offsetRight : '0',
        }}
      >
        {isDesktop && (
          <TopLeftResizeHandle
            size={size}
            setSize={setSize}
            variant={handleVariant}
            onResizeStart={handleResizeStart}
          />
        )}
        {children}
      </div>
    </>
  )
}

// ── Main overlay shell ────────────────────────────────────────────────────────
//
// Two independent panels:
//   • Ariel  (teal, right side)   — authenticated users only, via ChatContext.isOpen
//   • Eliya  (indigo, right side) — all users, via ChatContext.isEliyaOpen
//
// Opening one closes the other (enforced in ChatContext).

export function ChatOverlay() {
  const { isOpen, closeChat, isEliyaOpen, closeEliya, openChat } = useChat()
  const { user, loading } = useAuth()
  const pathname = usePathname()
  const [mounted, setMounted] = useState(false)

  // Ariel is only available once the profile is complete, and never on
  // onboarding routes — she is introduced AFTER onboarding, not during it.
  const profileCompleted =
    (user?.user_metadata as Record<string, unknown> | undefined)?.profile_completed === true
  const onOnboardingRoute = isOnOnboardingRoute(pathname)
  const arielAvailable    = Boolean(user) && profileCompleted && !onOnboardingRoute

  useEffect(() => { setMounted(true) }, [])

  // One-shot auto-open after onboarding completes: the hard redirect to
  // /?tab=overview arms the flag; consume it here and open Ariel, whose
  // greeting (seeded via OnboardingContext) welcomes the user by name.
  useEffect(() => {
    if (!mounted || !arielAvailable) return
    if (consumeArielWelcome()) openChat()
  }, [mounted, arielAvailable, openChat])

  if (!mounted || loading) return null

  return (
    <>
      {/* Ariel panel — teal Career Agent, completed-profile users only */}
      {arielAvailable && (
        <OverlayShell
          isOpen={isOpen}
          onBackdropClick={closeChat}
          ariaLabel="Ask Ariel — Career Agent"
          shadowColor="rgba(13,148,136,0.18)"
          handleVariant="onLight"
        >
          <ArielChat onClose={closeChat} />
        </OverlayShell>
      )}

      {/* Eliya panel — indigo Support, available to all users */}
      <OverlayShell
        isOpen={isEliyaOpen}
        onBackdropClick={closeEliya}
        handleVariant="onDark"
        ariaLabel="Ask Eliya — Support & Onboarding"
        shadowColor="rgba(79,70,229,0.18)"
      >
        <PublicChatPanel onClose={closeEliya} />
      </OverlayShell>
    </>
  )
}
