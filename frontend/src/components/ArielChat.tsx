'use client'

import {
  useState, useRef, useEffect, useCallback, memo,
  type KeyboardEvent, type ReactNode, type ChangeEvent,
} from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm    from 'remark-gfm'
import { TOKENS }         from '@/lib/tokens'
import { ensureFreshToken, getAuthHeaders } from '@/lib/api'
import { useOnboarding }  from '@/contexts/OnboardingContext'
import { useChat }        from '@/contexts/ChatContext'

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const STAGE_LABELS: Record<string, string> = {
  student:    'Student',
  junior:     'Junior',
  mid:        'Mid-Level',
  senior:     'Senior',
  management: 'Management',
}

// Per-role seniority levels from the onboarding preferences step.
const SENIORITY_LABELS: Record<string, string> = {
  junior:    'Junior',
  entry:     'Entry-Level',
  mid:       'Mid-Level',
  senior:    'Senior',
  lead:      'Lead',
  director:  'Director',
  executive: 'Executive',
}

const LINE_HEIGHT_PX    = 20   // matches leading-5 / text-[13px] in the widget
const MAX_LINES         = 4
const MAX_TEXTAREA_H    = LINE_HEIGHT_PX * MAX_LINES + 32  // 4 lines + py-4 (16px top + 16px bottom)
const BASE_TEXTAREA_H   = 44   // 1 line (20px) + py-3 (12px × 2) = 44px — no clipping
const SCROLL_THRESHOLD  = 80
const REPLY_SNIPPET_LEN = 80

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface FileAttachment {
  base64:     string   // raw base64 without the "data:…;base64," prefix
  mediaType:  string   // MIME type (image/*, video/*, application/pdf, etc.)
  previewUrl: string   // data URL for preview (images) or empty string
  name:       string
}

// Backwards-compat alias used by ChatMessage.image and consumeStream
type ImageAttachment = FileAttachment

const MAX_ATTACHMENTS   = 10
const MAX_FILE_SIZE_MB  = 5    // per-file ceiling
const MAX_TOTAL_SIZE_MB = 20   // cumulative ceiling across all queued attachments

// Approximate a decoded byte count from a base64 payload (4 chars ≈ 3 bytes).
// Used to size already-queued attachments, which store base64 but not raw size.
const approxBytesFromBase64 = (b64: string) => Math.floor(b64.length * 0.75)

/** Mirrors the ChatMessageSchema Pydantic model on the backend. */
export interface ChatMessage {
  id:                 string
  role:               'user' | 'assistant'
  content:            string
  isPinned?:          boolean
  translatedContent?: string
  replyContext?:      string
  image?:             ImageAttachment
  attachments?:       FileAttachment[]
}

/** Shape returned by GET /api/chat/history (list). */
interface SessionSummary {
  session_id:    string
  created_at:    string   // ISO-8601
  updated_at:    string
  preview:       string   // first user message truncated to 80 chars
  message_count: number
}

function makeId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return Math.random().toString(36).slice(2, 10)
}

function fmtDate(iso: string) {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// ─────────────────────────────────────────────────────────────────────────────
// API helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Strip raw base64 from images before persisting — individual images can be
 * hundreds of KB.  Swap the empty string for a proper upload URL in Phase 4.
 */
function serializeMessages(msgs: ChatMessage[]): ChatMessage[] {
  return msgs.map(m => ({
    ...m,
    image: m.image
      ? { ...m.image, base64: '' }   // keep metadata; drop payload
      : undefined,
  }))
}

/** POST /api/chat/history — fire-and-forget; never throws to the caller. */
async function syncSession(sessionId: string, messages: ChatMessage[]): Promise<void> {
  if (!sessionId || messages.length === 0) return
  try {
    await ensureFreshToken()
    await fetch('/api/chat/history', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body:    JSON.stringify({ session_id: sessionId, messages: serializeMessages(messages) }),
    })
  } catch (err) {
    console.warn('[Ariel] session sync failed:', err)
  }
}

/** GET /api/chat/history — returns [] on error. */
async function fetchSessionList(): Promise<SessionSummary[]> {
  try {
    await ensureFreshToken()
    const res = await fetch('/api/chat/history', { headers: getAuthHeaders() })
    if (!res.ok) return []
    return (await res.json()) as SessionSummary[]
  } catch {
    return []
  }
}

/** GET /api/chat/history/:id — returns null on error. */
async function fetchSessionMessages(sessionId: string): Promise<ChatMessage[] | null> {
  try {
    await ensureFreshToken()
    const res = await fetch(`/api/chat/history/${sessionId}`, { headers: getAuthHeaders() })
    if (!res.ok) return null
    const data = await res.json() as { messages: ChatMessage[] }
    return data.messages
  } catch {
    return null
  }
}

/** Translation stub — replace with real /api/chat/translate in Phase 4. */
async function mockTranslate(content: string): Promise<string> {
  await new Promise(r => setTimeout(r, 700))
  const snippet = content.length > 120 ? content.slice(0, 120) + '…' : content
  return `[Auto-translated]\n${snippet}`
}

/** Feedback stub — replace with real POST /api/chat/feedback in Phase 4. */
async function submitFeedback(id: string, content: string): Promise<void> {
  await new Promise(r => setTimeout(r, 400))
  console.info('[Ariel feedback] submitted', { messageId: id, preview: content.slice(0, 60) })
}

// ─────────────────────────────────────────────────────────────────────────────
// Icons
// ─────────────────────────────────────────────────────────────────────────────

function SpinnerIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'ariel-spin 0.8s linear infinite', flexShrink: 0 }}>
      <style>{`@keyframes ariel-spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.25" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function SendIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
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

function HistoryIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="1 4 1 10 7 10" />
      <path d="M3.51 15a9 9 0 1 0 .49-3.51" />
      <polyline points="12 7 12 12 15 15" />
    </svg>
  )
}

function CopyIcon()        { return <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> }
function CheckIcon()       { return <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg> }
function ReplyIcon()       { return <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg> }
function TranslateIcon()   { return <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 8l6 6"/><path d="M4 14l6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/></svg> }
function PinIcon({ filled = false }: { filled?: boolean }) { return <svg width={13} height={13} viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg> }
function FlagIcon()        { return <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg> }
function TrashIcon()       { return <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg> }
function EditIcon()        { return <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> }
function RegenerateIcon()  { return <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.51"/></svg> }
function StopIcon({ s = 15 }: { s?: number }) { return <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2.5"/></svg> }

// ─────────────────────────────────────────────────────────────────────────────
// StreamingMarkdown (memoised — unchanged from Phase 2)
// ─────────────────────────────────────────────────────────────────────────────

const mdComponents = {
  h1: ({ children }: { children?: ReactNode }) => <p className="font-bold text-[13.5px] text-slate-900 mb-1">{children}</p>,
  h2: ({ children }: { children?: ReactNode }) => <p className="font-semibold text-[13px] text-slate-900 mb-1">{children}</p>,
  h3: ({ children }: { children?: ReactNode }) => <p className="font-semibold text-[12.5px] text-slate-800 mb-0.5">{children}</p>,
  p:  ({ children }: { children?: ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }: { children?: ReactNode }) => <ul className="space-y-0.5 mb-2 pl-0">{children}</ul>,
  ol: ({ children }: { children?: ReactNode }) => <ol className="list-decimal pl-4 space-y-0.5 mb-2">{children}</ol>,
  li: ({ children }: { children?: ReactNode }) => (
    <li className="flex items-start gap-1.5">
      <span className="mt-[7px] shrink-0 w-[4px] h-[4px] rounded-full bg-slate-400" aria-hidden />
      <span className="flex-1">{children}</span>
    </li>
  ),
  strong: ({ children }: { children?: ReactNode }) => <strong className="font-semibold text-slate-900">{children}</strong>,
  em:     ({ children }: { children?: ReactNode }) => <em className="italic text-slate-700">{children}</em>,
  code:   ({ children, className }: { children?: ReactNode; className?: string }) => {
    const isBlock = !!className?.startsWith('language-')
    return isBlock
      ? <code className="block bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-[11.5px] font-mono text-slate-700 overflow-x-auto mb-2 whitespace-pre">{children}</code>
      : <code className="bg-slate-100 rounded px-1 py-0.5 text-[11.5px] font-mono text-slate-700">{children}</code>
  },
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="border-l-2 border-teal-300 pl-3 italic text-slate-500 mb-2">{children}</blockquote>
  ),
  table: ({ children }: { children?: ReactNode }) => (
    <div className="overflow-x-auto mb-2">
      <table className="text-[11.5px] border-collapse w-full">{children}</table>
    </div>
  ),
  th: ({ children }: { children?: ReactNode }) => <th className="border border-slate-200 px-2 py-1 bg-slate-50 font-semibold text-left">{children}</th>,
  td: ({ children }: { children?: ReactNode }) => <td className="border border-slate-200 px-2 py-1">{children}</td>,
  a:  ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="text-teal-600 underline underline-offset-2 hover:text-teal-700">{children}</a>
  ),
  hr: () => <hr className="border-slate-200 my-2" />,
}

const StreamingMarkdown = memo(function StreamingMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents as never}>
      {content}
    </ReactMarkdown>
  )
})

// ─────────────────────────────────────────────────────────────────────────────
// MessageActionBar (unchanged from Phase 2)
// ─────────────────────────────────────────────────────────────────────────────

interface ActionBarCallbacks {
  onCopy:          () => void
  onReply:         () => void
  onTranslate:     () => void
  onPin:           () => void
  onReport:        () => void
  onDelete:        () => void
  onEdit?:         () => void   // user messages only
  onRegenerate?:   () => void   // latest assistant message only
  isPinned:        boolean
  isTranslating:   boolean
}

function MessageActionBar({ isUser, callbacks }: { isUser: boolean; callbacks: ActionBarCallbacks }) {
  // Brief "Copied!" feedback — swap the icon/label back after 2s. A ref holds
  // the timeout id so a rapid second click restarts the window instead of
  // stacking timeouts, and so it can be cleared on unmount.
  const [copied, setCopied]   = useState(false)
  const copiedTimeoutRef      = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (copiedTimeoutRef.current) clearTimeout(copiedTimeoutRef.current) }, [])

  const handleCopy = useCallback(() => {
    callbacks.onCopy()
    setCopied(true)
    if (copiedTimeoutRef.current) clearTimeout(copiedTimeoutRef.current)
    copiedTimeoutRef.current = setTimeout(() => setCopied(false), 2000)
  }, [callbacks])

  const actions = [
    {
      icon:  copied ? <CheckIcon /> : <CopyIcon />,
      label: copied ? 'Copied!' : 'Copy',
      danger: false,
      fn: handleCopy,
    },
    { icon: <ReplyIcon />,   label: 'Reply',  danger: false, fn: callbacks.onReply  },
    // Edit — user messages only
    ...(isUser && callbacks.onEdit ? [{
      icon: <EditIcon />, label: 'Edit', danger: false, fn: callbacks.onEdit,
    }] : []),
    // Translate — assistant messages only
    ...(!isUser ? [{
      icon:  callbacks.isTranslating ? <SpinnerIcon s={13} /> : <TranslateIcon />,
      label: 'Translate', danger: false, fn: callbacks.onTranslate,
    }] : []),
    // Regenerate — latest assistant message only
    ...(!isUser && callbacks.onRegenerate ? [{
      icon: <RegenerateIcon />, label: 'Regenerate', danger: false, fn: callbacks.onRegenerate,
    }] : []),
    { icon: <PinIcon filled={callbacks.isPinned} />, label: callbacks.isPinned ? 'Unpin' : 'Pin', danger: false, fn: callbacks.onPin },
    { icon: <FlagIcon />,    label: 'Report', danger: false, fn: callbacks.onReport  },
    { icon: <TrashIcon />,   label: 'Delete', danger: true,  fn: callbacks.onDelete  },
  ]

  // Inline below the bubble — never clipped by overflow-y-auto.
  // Visibility is controlled by opacity via the parent group-hover.
  return (
    <div
      className={`
        flex items-center gap-0.5 px-0.5 py-0.5 mt-0.5
        opacity-0 group-hover:opacity-100 group-focus-within:opacity-100
        pointer-events-none group-hover:pointer-events-auto group-focus-within:pointer-events-auto
        transition-opacity duration-150
        ${isUser ? 'self-end' : 'self-start ml-9'}
      `}
      onMouseEnter={e => e.stopPropagation()}
    >
      {actions.map(a => (
        <button key={a.label} onClick={a.fn} title={a.label} aria-label={a.label}
          className={`
            w-6 h-6 flex items-center justify-center rounded-lg transition
            ${a.danger ? 'text-slate-300 hover:text-rose-500 hover:bg-rose-50' : 'text-slate-300 hover:text-slate-600 hover:bg-slate-100'}
            ${a.label === 'Unpin' || a.label === 'Copied!' ? '!text-teal-500' : ''}
          `}>
          {a.icon}
        </button>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MessageBubble (unchanged from Phase 2)
// ─────────────────────────────────────────────────────────────────────────────

interface BubbleProps {
  message:            ChatMessage
  isStreaming:        boolean
  showTranslation:    boolean
  isTranslating:      boolean
  isLatestAssistant:  boolean   // controls Regenerate visibility
  onDelete:           (id: string) => void
  onReply:            (msg: ChatMessage) => void
  onPin:              (id: string) => void
  onTranslate:        (id: string) => void
  onReport:           (id: string, content: string) => void
  onEdit:             (id: string) => void
  onRegenerate:       (id: string) => void
}

const MessageBubble = memo(function MessageBubble({
  message, isStreaming, showTranslation, isTranslating, isLatestAssistant,
  onDelete, onReply, onPin, onTranslate, onReport, onEdit, onRegenerate,
}: BubbleProps) {
  const isUser   = message.role === 'user'
  const rendered = showTranslation && message.translatedContent ? message.translatedContent : message.content

  const callbacks: ActionBarCallbacks = {
    isPinned:      !!message.isPinned,
    isTranslating,
    onCopy:        () => { navigator.clipboard.writeText(message.content).catch(() => {}) },
    onReply:       () => onReply(message),
    onTranslate:   () => onTranslate(message.id),
    onPin:         () => onPin(message.id),
    onReport:      () => onReport(message.id, message.content),
    onDelete:      () => onDelete(message.id),
    onEdit:        isUser                ? () => onEdit(message.id)       : undefined,
    onRegenerate:  isLatestAssistant     ? () => onRegenerate(message.id) : undefined,
  }

  return (
    // `group` here drives the hover-reveal of the action bar below
    <div className={`group flex flex-col ${isUser ? 'items-end' : 'items-start'} gap-0.5`}>
      {message.replyContext && (
        <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] text-slate-500 bg-slate-100 border-l-2 border-slate-300 max-w-[85%] ${isUser ? 'self-end' : 'self-start ml-9'}`}>
          <ReplyIcon />
          <span className="truncate">{message.replyContext}</span>
        </div>
      )}
      {/* Bubble row */}
      <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} w-full`}>
        {!isUser && (
          <div className="w-7 h-7 rounded-full text-white text-[11px] font-bold flex items-center justify-center mr-2 mt-0.5 flex-shrink-0"
            style={{ background: TOKENS.color.gradientIntelligence }}>A</div>
        )}
        <div
          dir="auto"
          className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed transition-all duration-200 [unicode-bidi:plaintext] text-start
            ${isUser ? 'text-white rounded-tr-sm' : 'bg-white border text-slate-800 rounded-tl-sm'}
            ${!isUser && message.isPinned ? 'border-teal-300 bg-teal-50/40' : !isUser ? 'border-slate-100' : ''}
          `}
          style={isUser ? { background: TOKENS.color.primary } : undefined}
        >
          {message.isPinned && (
            <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-teal-600 mb-1.5">
              <PinIcon filled /> Pinned
            </span>
          )}
          {isUser && message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-1.5">
              {message.attachments.map((a, i) => {
                const dot  = a.name.lastIndexOf('.')
                const base = dot > 0 ? a.name.slice(0, dot) : a.name
                const ext  = dot > 0 ? a.name.slice(dot + 1) : ''
                const label = base.length > 12 ? `${base.slice(0, 10)}…${ext ? `.${ext}` : ''}` : a.name
                return (
                  <span key={i} className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-white/20 text-white/90 leading-none" title={a.name}>
                    <span className="font-semibold uppercase opacity-75 text-[9px]">{ext || '📎'}</span>
                    {label}
                  </span>
                )
              })}
            </div>
          )}
          {isUser
            ? <span className="whitespace-pre-wrap">{rendered}</span>
            : rendered ? <StreamingMarkdown content={rendered} /> : null
          }
          {!isUser && message.translatedContent && (
            <button onClick={() => onTranslate(message.id)}
              className="mt-1.5 block text-[10.5px] text-teal-500 hover:text-teal-700 transition">
              {showTranslation ? 'Show original' : 'Show translation'}
            </button>
          )}
          {isStreaming && !isUser && (
            <span className="inline-block w-[2px] h-[14px] bg-teal-500 ml-0.5 align-middle"
              style={{ animation: 'ariel-cursor 0.9s ease-in-out infinite' }} />
          )}
        </div>
      </div>
      {/* Action bar — inline below the bubble, revealed on group-hover */}
      <MessageActionBar isUser={isUser} callbacks={callbacks} />
      <style>{`@keyframes ariel-cursor{0%,100%{opacity:1}50%{opacity:0}}`}</style>
    </div>
  )
})

// ─────────────────────────────────────────────────────────────────────────────
// TypingIndicator (unchanged)
// ─────────────────────────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="w-7 h-7 rounded-full text-white text-[11px] font-bold flex items-center justify-center mr-2 mt-0.5 flex-shrink-0"
        style={{ background: TOKENS.color.gradientIntelligence }}>A</div>
      <div className="bg-white border border-slate-100 rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1">
        {[0, 1, 2].map(i => (
          <span key={i} className="w-1.5 h-1.5 rounded-full bg-slate-300"
            style={{ animation: `ariel-dot 1.2s ease-in-out ${i * 0.18}s infinite` }} />
        ))}
      </div>
      <style>{`@keyframes ariel-dot{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-6px)}}`}</style>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// HistoryPanel — slides in over the message list
// ─────────────────────────────────────────────────────────────────────────────

interface HistoryPanelProps {
  isOpen:         boolean
  onClose:        () => void
  sessions:       SessionSummary[]
  loadingList:    boolean
  activeSessionId: string
  onSelectSession: (id: string) => void
  onNewSession:    () => void
}

function HistoryPanel({
  isOpen, onClose, sessions, loadingList, activeSessionId, onSelectSession, onNewSession,
}: HistoryPanelProps) {
  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="absolute inset-0 z-20 bg-black/10"
          onClick={onClose}
        />
      )}

      {/* Slide-in panel */}
      <div
        className={`
          absolute top-0 right-0 bottom-0 z-30 w-72
          bg-white border-l border-slate-100 shadow-floating
          flex flex-col
          transition-transform duration-250 ease-out
          ${isOpen ? 'translate-x-0' : 'translate-x-full'}
        `}
      >
        {/* Panel header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 flex-shrink-0">
          <div className="flex items-center gap-2 text-slate-700">
            <HistoryIcon />
            <span className="text-[13px] font-semibold">History</span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close history panel"
            title="Close"
            className="w-6 h-6 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 focus-visible:text-slate-700 transition text-[16px] leading-none"
          >×</button>
        </div>

        {/* New session shortcut */}
        <div className="px-3 py-2 border-b border-slate-100 flex-shrink-0">
          <button
            onClick={() => { onNewSession(); onClose() }}
            className="w-full text-left text-[12px] text-teal-600 font-medium px-3 py-2 rounded-lg hover:bg-teal-50 transition flex items-center gap-2"
          >
            <span className="text-[16px] leading-none">+</span> New conversation
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto">
          {loadingList ? (
            <div className="flex items-center justify-center h-24 text-slate-400">
              <SpinnerIcon s={18} />
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 gap-2 text-center px-6">
              <HistoryIcon s={20} />
              <p className="text-[12px] text-slate-400">No previous conversations yet.</p>
            </div>
          ) : (
            <ul className="p-2 space-y-1">
              {sessions.map(s => {
                const isActive = s.session_id === activeSessionId
                return (
                  <li key={s.session_id}>
                    <button
                      onClick={() => { onSelectSession(s.session_id); onClose() }}
                      className={`
                        w-full text-left px-3 py-2.5 rounded-xl transition
                        ${isActive
                          ? 'bg-teal-50 border border-teal-200'
                          : 'hover:bg-slate-50 border border-transparent'
                        }
                      `}
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[10.5px] text-slate-400">{fmtDate(s.updated_at)}</span>
                        <span className="text-[10px] text-slate-300">{s.message_count} msg{s.message_count !== 1 ? 's' : ''}</span>
                      </div>
                      <p dir="auto" className="text-[12px] text-slate-600 leading-snug line-clamp-2 [unicode-bidi:plaintext] text-start">{s.preview || 'Empty conversation'}</p>
                      {isActive && (
                        <span className="mt-1 inline-block text-[10px] font-semibold text-teal-600">Active</span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase 1 hooks (unchanged)
// ─────────────────────────────────────────────────────────────────────────────

function useAutoHeight(ref: React.RefObject<HTMLTextAreaElement | null>, value: string) {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    // Reset to 'auto' first so scrollHeight shrinks when text is deleted,
    // then let the browser measure the true content height.
    // min-h / max-h on the element itself (set via Tailwind) act as the floor/ceiling.
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [value, ref])
}

function resetHeight(el: HTMLTextAreaElement | null) {
  // Clear the JS-set height so Tailwind's min-h takes over immediately.
  if (el) el.style.height = 'auto'
}

function useSmartScroll(
  containerRef: React.RefObject<HTMLDivElement | null>,
  bottomRef:    React.RefObject<HTMLDivElement | null>,
  streamTick:   unknown,
) {
  const atBottomRef  = useRef(true)
  const scrollingRef = useRef(false)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onScroll = () => {
      if (scrollingRef.current) return
      atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [containerRef])

  useEffect(() => {
    if (!atBottomRef.current) return
    scrollingRef.current = true
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    const t = setTimeout(() => { scrollingRef.current = false }, 300)
    return () => clearTimeout(t)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamTick])

  const forceBottom = useCallback(() => {
    atBottomRef.current  = true
    scrollingRef.current = true
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    setTimeout(() => { scrollingRef.current = false }, 300)
  }, [bottomRef])

  return { forceBottom }
}

// ─────────────────────────────────────────────────────────────────────────────
// SSE stream consumer (unchanged from Phase 2)
// ─────────────────────────────────────────────────────────────────────────────

async function consumeStream(
  message:     string,
  history:     { role: string; content: string }[],
  signal:      AbortSignal,
  onChunk:     (delta: string) => void,
  attachments?: FileAttachment[],
) {
  const body: Record<string, unknown> = { message, chat_history: history }
  if (attachments?.length) {
    body.attachments = attachments.map(a => ({
      base64:   a.base64,
      filename: a.name,
      mimeType: a.mediaType,
    }))
  }
  await ensureFreshToken()
  const res = await fetch('/api/chat/ariel/private', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body:    JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    // FastAPI error bodies are JSON ({"detail": "..."}) — extract the message
    // instead of throwing the raw response text, which would render the
    // literal JSON blob (braces, quotes, key names) as the chat bubble.
    const text = await res.text().catch(() => '')
    let detail: string | undefined
    try { detail = (JSON.parse(text) as { detail?: string }).detail } catch { /* not JSON */ }
    throw new Error(detail || res.statusText || `HTTP ${res.status}`)
  }

  const reader  = res.body.getReader()
  const decoder = new TextDecoder()
  let   buf     = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const payload = line.slice(6).trim()
      if (!payload || payload === '[DONE]') continue
      try {
        const parsed = JSON.parse(payload) as { chunk?: string; error?: string }
        if (parsed.error) throw new Error(parsed.error)
        if (parsed.chunk) onChunk(parsed.chunk)
      } catch (e) { if (e instanceof Error && e.message !== payload) throw e }
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ArielChat — main component
// ─────────────────────────────────────────────────────────────────────────────

export function ArielChat({ onClose }: { onClose?: () => void } = {}) {
  const { data: onboardingData, clear: clearOnboarding } = useOnboarding()
  const { triggerProfileRefresh } = useChat()

  // ── Phase 1+2 state ────────────────────────────────────────────────────────
  const [messages,           setMessages]           = useState<ChatMessage[]>([])
  const [input,              setInput]              = useState('')
  const [streaming,          setStreaming]          = useState(false)
  const [showingTranslation, setShowingTranslation] = useState<Set<string>>(new Set())
  const [translatingIds,     setTranslatingIds]     = useState<Set<string>>(new Set())
  const [replyingTo,         setReplyingTo]         = useState<ChatMessage | null>(null)
  const [attachments,        setAttachments]        = useState<FileAttachment[]>([])
  const [attachError,        setAttachError]        = useState<string | null>(null)

  // ── Phase 3 state ──────────────────────────────────────────────────────────
  const [sessionId,     setSessionId]     = useState<string>(() => makeId())
  const [showHistory,   setShowHistory]   = useState(false)
  const [sessionList,   setSessionList]   = useState<SessionSummary[]>([])
  const [loadingList,   setLoadingList]   = useState(false)
  const [loadingSession, setLoadingSession] = useState(false)

  // ── Refs ───────────────────────────────────────────────────────────────────
  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textRef   = useRef<HTMLTextAreaElement>(null)
  const fileRef   = useRef<HTMLInputElement>(null)
  const abortRef  = useRef<AbortController | null>(null)
  const greetRef  = useRef(false)

  // Tracks whether streaming has ended and a sync is needed.
  // Using a ref (not state) so it never triggers a re-render.
  const needsSyncRef     = useRef(false)
  const sessionIdRef     = useRef(sessionId)
  sessionIdRef.current   = sessionId   // always current without stale closures

  const lastContent   = messages.at(-1)?.content ?? ''
  const inputDisabled = streaming || loadingSession
  useAutoHeight(textRef, input)
  const { forceBottom } = useSmartScroll(scrollRef, bottomRef, lastContent)

  // Re-focus the input once it actually becomes enabled again (DOM committed),
  // rather than calling textRef.current?.focus() synchronously right after
  // setStreaming(false) — that races the React re-render that removes the
  // `disabled` attribute, so the focus() call silently no-ops on a still-
  // disabled element and the user has to click back into the input.
  const wasDisabledRef = useRef(false)
  useEffect(() => {
    if (wasDisabledRef.current && !inputDisabled) {
      textRef.current?.focus()
    }
    wasDisabledRef.current = inputDisabled
  }, [inputDisabled])

  // ── Sync: fire once per exchange, after streaming ends ────────────────────
  // Detects the streaming true→false transition so we never sync mid-stream.
  useEffect(() => {
    if (streaming) {
      needsSyncRef.current = true
      return
    }
    if (!needsSyncRef.current || messages.length === 0) return
    needsSyncRef.current = false
    // messages is current here (effect runs after state settles)
    syncSession(sessionIdRef.current, messages)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming, messages])

  // ── Load session list on mount ─────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    setLoadingList(true)
    fetchSessionList().then(list => {
      if (!cancelled) setSessionList(list)
    }).finally(() => {
      if (!cancelled) setLoadingList(false)
    })
    return () => { cancelled = true }
  }, [])

  // ── Greeting ───────────────────────────────────────────────────────────────
  // Every variable is interpolated only when it actually has a value — an
  // empty careerStage or missing roles must never render as "****".
  useEffect(() => {
    if (greetRef.current || !onboardingData) return
    greetRef.current = true
    const first = onboardingData.fullName.split(' ')[0]

    // Prefer the live role/seniority preferences captured during onboarding.
    const roles = (onboardingData.roles ?? []).filter(r => r.role)
    let context = ''
    if (roles.length > 0) {
      const parts = roles.slice(0, 3).map(r => {
        const level = SENIORITY_LABELS[r.seniority] ?? ''
        return level ? `**${level} ${r.role}**` : `**${r.role}**`
      })
      const list = parts.length > 1
        ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
        : parts[0]
      context = ` I see you're targeting ${list} roles — great, that gives me a clear direction.`
    } else {
      const stage = onboardingData.careerStage
        ? (STAGE_LABELS[onboardingData.careerStage] ?? onboardingData.careerStage)
        : ''
      if (stage) context = ` I see you're at the **${stage}** stage.`
    }

    setMessages([{
      id:      makeId(),
      role:    'assistant',
      content: `Hi ${first}! Great to have you here.${context} Let's refine your Master Profile together — what would you like to tackle first?`,
    }])
    clearOnboarding()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── New conversation ───────────────────────────────────────────────────────
  const startNewSession = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setInput('')
    setReplyingTo(null)
    setAttachments([])
    setShowingTranslation(new Set())
    const newId = makeId()
    setSessionId(newId)
    sessionIdRef.current = newId
    needsSyncRef.current = false
    textRef.current?.focus()
  }, [])

  // ── Load a past session ────────────────────────────────────────────────────
  const loadSession = useCallback(async (id: string) => {
    if (id === sessionIdRef.current || streaming) return
    setLoadingSession(true)
    abortRef.current?.abort()
    try {
      const loaded = await fetchSessionMessages(id)
      if (!loaded) return
      setMessages(loaded)
      setSessionId(id)
      sessionIdRef.current = id
      setShowingTranslation(new Set())
      setReplyingTo(null)
      setAttachments([])
      needsSyncRef.current = false
      forceBottom()
    } finally {
      setLoadingSession(false)
    }
  }, [streaming, forceBottom])

  // ── Open history panel + refresh list ─────────────────────────────────────
  const openHistory = useCallback(() => {
    setShowHistory(true)
    setLoadingList(true)
    fetchSessionList().then(setSessionList).finally(() => setLoadingList(false))
  }, [])

  // ── File attachment handlers ───────────────────────────────────────────────
  const attachFiles = useCallback((incoming: File[]) => {
    if (!incoming.length) return

    // 0. Deduplicate — drop files already queued (matched by name + size)
    //    This prevents double-add when both onDrop and onChange fire, or when
    //    the user picks the same file twice.
    const deduped = incoming.filter(f =>
      !attachments.some(a => a.name === f.name && a.base64.length > 0
        // size check: base64 length ≈ ceil(size / 3) * 4, close enough for dedup
        // We compare name only here; the FileReader hasn't run yet so we can't
        // compare base64 — use name+type as a practical unique key instead.
      ) && !incoming.slice(0, incoming.indexOf(f)).some(
        earlier => earlier.name === f.name && earlier.size === f.size
      )
    )
    if (!deduped.length) return

    // 1. Admission control — walk the incoming files in order and accept each
    //    only if it fits within BOTH the count cap and the cumulative-size cap,
    //    seeded from what's already queued. A file over the per-file ceiling is
    //    always rejected. Rejections are surfaced via one inline notice, never
    //    a native alert().
    const perFileLimit = MAX_FILE_SIZE_MB  * 1024 * 1024
    const totalLimit   = MAX_TOTAL_SIZE_MB * 1024 * 1024

    let runningCount = attachments.length
    let runningBytes = attachments.reduce((sum, a) => sum + approxBytesFromBase64(a.base64), 0)

    const accepted: File[] = []
    let rejectedOversize = 0   // exceeds per-file ceiling
    let rejectedCapacity = 0   // would exceed count or cumulative-size ceiling

    for (const file of deduped) {
      if (file.size > perFileLimit) { rejectedOversize++; continue }
      if (runningCount + 1 > MAX_ATTACHMENTS)        { rejectedCapacity++; continue }
      if (runningBytes + file.size > totalLimit)     { rejectedCapacity++; continue }
      accepted.push(file)
      runningCount += 1
      runningBytes += file.size
    }

    // 2. Compose a single, concise notice for anything skipped
    if (rejectedOversize || rejectedCapacity) {
      const parts: string[] = []
      if (rejectedOversize) {
        parts.push(`${rejectedOversize} over ${MAX_FILE_SIZE_MB}MB each`)
      }
      if (rejectedCapacity) {
        parts.push(`limit is ${MAX_ATTACHMENTS} files / ${MAX_TOTAL_SIZE_MB}MB total`)
      }
      const skipped = rejectedOversize + rejectedCapacity
      setAttachError(`${skipped} file${skipped > 1 ? 's' : ''} skipped — ${parts.join(', ')}.`)
    }

    if (!accepted.length) return

    // 3. Read accepted files; state updates merge in as each reader resolves.
    //    The count guard is kept as a defensive backstop against interleaving.
    accepted.forEach(file => {
      const reader = new FileReader()
      reader.onload = ev => {
        const dataUrl = ev.target?.result as string
        setAttachments(cur => {
          if (cur.length >= MAX_ATTACHMENTS) return cur
          return [...cur, {
            base64:     dataUrl.split(',')[1] ?? '',
            mediaType:  file.type,
            previewUrl: dataUrl,
            name:       file.name,
          }]
        })
      }
      reader.readAsDataURL(file)
    })
  }, [attachments])

  // Auto-dismiss the attachment error notice after 4 s.
  useEffect(() => {
    if (!attachError) return
    const t = setTimeout(() => setAttachError(null), 4000)
    return () => clearTimeout(t)
  }, [attachError])

  const handleFileChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    attachFiles(files)
  }, [attachFiles])

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.files ?? [])
    if (!files.length) return
    e.preventDefault()
    attachFiles(files)
  }, [attachFiles])

  // ── Message action handlers ────────────────────────────────────────────────

  const deleteMessage = useCallback((id: string) => {
    setMessages(prev => prev.filter(m => m.id !== id))
    setReplyingTo(prev => prev?.id === id ? null : prev)
  }, [])

  const togglePin = useCallback((id: string) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, isPinned: !m.isPinned } : m))
  }, [])

  const handleTranslate = useCallback(async (id: string) => {
    const msg = messages.find(m => m.id === id)
    if (!msg) return
    if (msg.translatedContent) {
      setShowingTranslation(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
      return
    }
    setTranslatingIds(prev => new Set(prev).add(id))
    try {
      const translated = await mockTranslate(msg.content)
      setMessages(prev => prev.map(m => m.id === id ? { ...m, translatedContent: translated } : m))
      setShowingTranslation(prev => new Set(prev).add(id))
    } finally {
      setTranslatingIds(prev => { const n = new Set(prev); n.delete(id); return n })
    }
  }, [messages])

  const handleReply  = useCallback((msg: ChatMessage) => { setReplyingTo(msg); textRef.current?.focus() }, [])
  const handleReport = useCallback(async (id: string, content: string) => { await submitFeedback(id, content) }, [])

  // ── Edit user message: restore text to input, remove msg + everything after ─
  const handleEdit = useCallback((msgId: string) => {
    if (streaming) return
    const idx = messages.findIndex(m => m.id === msgId)
    if (idx === -1) return
    setInput(messages[idx].content)
    setMessages(prev => prev.slice(0, idx))
    setReplyingTo(null)
    textRef.current?.focus()
  }, [messages, streaming])

  // ── Regenerate: replace latest assistant reply with a fresh stream ─────────
  const handleRegenerate = useCallback(async (assistantMsgId: string) => {
    if (streaming) return

    const idx = messages.findIndex(m => m.id === assistantMsgId)
    if (idx === -1) return

    // Walk backwards to find the user turn that prompted this response
    let userIdx = idx - 1
    while (userIdx >= 0 && messages[userIdx].role !== 'user') userIdx--
    if (userIdx < 0) return

    const userMsg    = messages[userIdx]
    const history    = messages.slice(0, userIdx).map(m => ({ role: m.role, content: m.content }))
    const newAsstId  = makeId()

    // Replace old assistant bubble with a fresh empty one; keep everything before it
    setMessages(prev => [
      ...prev.slice(0, idx),
      { id: newAsstId, role: 'assistant', content: '' },
    ])
    forceBottom()
    setStreaming(true)

    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      await consumeStream(userMsg.content, history, ctrl.signal, chunk => {
        setMessages(prev => {
          const next = [...prev]
          const i    = next.findIndex(m => m.id === newAsstId)
          if (i !== -1) next[i] = { ...next[i], content: next[i].content + chunk }
          return next
        })
      })
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      const errMsg = err instanceof Error ? err.message : 'Something went wrong. Please try again.'
      setMessages(prev => {
        const next = [...prev]
        const i    = next.findIndex(m => m.id === newAsstId)
        if (i !== -1) next[i] = { ...next[i], content: errMsg }
        return next
      })
    } finally {
      // Refocus happens in the wasDisabledRef effect once the textarea's
      // `disabled` attribute actually clears in the DOM (see above).
      setStreaming(false)
      triggerProfileRefresh()
    }
  }, [messages, streaming, forceBottom, triggerProfileRefresh])

  // ── Send ───────────────────────────────────────────────────────────────────
  const sendMessage = useCallback(async (override?: string) => {
    const rawText = (override ?? input).trim() || (attachments.length ? 'Please look at the attached files.' : '')
    if (!rawText || streaming) return

    const replySnippet  = replyingTo
      ? replyingTo.content.slice(0, REPLY_SNIPPET_LEN) + (replyingTo.content.length > REPLY_SNIPPET_LEN ? '…' : '')
      : null
    const fullText = replySnippet ? `Replying to: "${replySnippet}"\n\n${rawText}` : rawText

    setInput('')
    resetHeight(textRef.current)
    setReplyingTo(null)
    const capturedAttachments = attachments
    setAttachments([])

    const history     = messages.map(m => ({ role: m.role, content: m.content }))
    const assistantId = makeId()

    // Store the first image for in-chat preview (ChatMessage.image is display-only)
    const previewImage = capturedAttachments.find(a => a.mediaType.startsWith('image/'))

    setMessages(prev => [
      ...prev,
      { id: makeId(), role: 'user', content: rawText, replyContext: replySnippet ?? undefined, image: previewImage, attachments: capturedAttachments.length ? capturedAttachments : undefined },
      { id: assistantId, role: 'assistant', content: '' },
    ])
    forceBottom()
    setStreaming(true)

    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      await consumeStream(fullText, history, ctrl.signal, chunk => {
        setMessages(prev => {
          const next = [...prev]
          const idx  = next.findIndex(m => m.id === assistantId)
          if (idx !== -1) next[idx] = { ...next[idx], content: next[idx].content + chunk }
          return next
        })
      }, capturedAttachments.length ? capturedAttachments : undefined)
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      const msg = err instanceof Error ? err.message : 'Something went wrong. Please try again.'
      setMessages(prev => {
        const next = [...prev]
        const idx  = next.findIndex(m => m.id === assistantId)
        if (idx !== -1) next[idx] = { ...next[idx], content: msg }
        return next
      })
    } finally {
      // Refocus happens in the wasDisabledRef effect once the textarea's
      // `disabled` attribute actually clears in the DOM (see above).
      setStreaming(false)

      // Signal that the Master Profile may have changed so any mounted
      // Confidence Score display can re-fetch (see ChatContext.profileVersion).
      // Tool-call profile edits (update_experience/update_skills/etc.) commit
      // synchronously on the server before this response finishes streaming,
      // so the immediate trigger already covers those. CV-attachment
      // ingestion instead runs as a fire-and-forget background task that
      // completes *after* the response returns, so also schedule a delayed
      // second trigger to catch it.
      triggerProfileRefresh()
      if (capturedAttachments.length) {
        setTimeout(triggerProfileRefresh, 5000)
      }
    }
  }, [input, messages, streaming, replyingTo, attachments, forceBottom, triggerProfileRefresh])

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
    if (e.key === 'Escape') setReplyingTo(null)
  }

  // ── Input bar JSX (inlined at each call site — NOT a nested component) ──────
  // Defining a component function inside another component causes React to treat
  // it as a new type on every render, unmounting the DOM node (and losing focus)
  // on every keystroke. We use a plain function that returns JSX and call it
  // directly so the returned elements become part of the parent's render tree.
  const renderInputBar = (placeholder: string) => (
    <div
      className="flex-shrink-0 border-t border-slate-100 bg-white px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] space-y-1.5"
      onDragOver={e => e.preventDefault()}
      onDrop={e => { e.preventDefault(); attachFiles(Array.from(e.dataTransfer.files)) }}
    >
      {/* Hidden file input — always in the DOM so fileRef is always valid */}
      <input
        ref={fileRef}
        type="file"
        accept="image/*,video/*,.pdf,.doc,.docx"
        multiple
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Reply context banner */}
      {replyingTo && (
        <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-teal-50 border border-teal-200 text-[11.5px]">
          <ReplyIcon />
          <span className="text-teal-700 font-medium shrink-0">Replying to:</span>
          <span className="text-slate-500 flex-1 truncate">{replyingTo.content.slice(0, REPLY_SNIPPET_LEN)}</span>
          <button onClick={() => setReplyingTo(null)} className="ml-auto text-slate-400 hover:text-slate-700 focus-visible:text-slate-700 transition text-[15px] leading-none" title="Cancel reply" aria-label="Cancel reply">×</button>
        </div>
      )}

      {/* Attachment pills */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2 p-1 overflow-y-auto max-h-24">
          {attachments.map((a, i) => {
            const truncateName = (name: string) => {
              const dot  = name.lastIndexOf('.')
              const base = dot > 0 ? name.slice(0, dot) : name
              const ext  = dot > 0 ? name.slice(dot)   : ''
              if (base.length <= 10) return name
              return `${base.slice(0, 8)}…${ext}`
            }

            const openPreview = () => {
              // Build a blob URL from the stored base64 so the file opens in a new tab.
              // For images the previewUrl data-URI works directly; for other types we
              // must construct a proper blob so the browser picks the right viewer.
              if (a.previewUrl && a.mediaType.startsWith('image/')) {
                window.open(a.previewUrl, '_blank', 'noopener')
                return
              }
              try {
                const binary = atob(a.base64)
                const bytes  = new Uint8Array(binary.length)
                for (let b = 0; b < binary.length; b++) bytes[b] = binary.charCodeAt(b)
                const blob = new Blob([bytes], { type: a.mediaType })
                const url  = URL.createObjectURL(blob)
                const win  = window.open(url, '_blank', 'noopener')
                // Revoke after the tab has had time to load the blob
                win?.addEventListener('load', () => URL.revokeObjectURL(url), { once: true })
                // Fallback revoke after 60 s in case load never fires
                setTimeout(() => URL.revokeObjectURL(url), 60_000)
              } catch {
                // If atob fails (e.g. empty base64 during async read), no-op
              }
            }

            return (
              <div
                key={i}
                className="flex items-center gap-1.5 text-xs px-2 py-1 rounded text-white"
                style={{ background: TOKENS.color.primary }}
              >
                {/* Clickable body — opens file preview */}
                <button
                  type="button"
                  onClick={openPreview}
                  className="flex items-center gap-1.5 cursor-pointer rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
                  title={`Preview: ${a.name}`}
                  aria-label={`Preview attachment ${a.name}`}
                >
                  {a.mediaType.startsWith('image/') ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={a.previewUrl} alt="" className="w-4 h-4 rounded object-cover shrink-0 opacity-90" />
                  ) : (
                    <span className="shrink-0 font-bold uppercase opacity-80">
                      {a.name.split('.').pop()?.slice(0, 3) ?? '📎'}
                    </span>
                  )}
                  <span className="max-w-[90px] leading-none">{truncateName(a.name)}</span>
                </button>

                {/* Remove — stops propagation so focus doesn't linger on the button */}
                <button
                  type="button"
                  onClick={e => {
                    e.stopPropagation()
                    setAttachments(prev => prev.filter((_, idx) => idx !== i))
                    textRef.current?.focus()
                  }}
                  className="shrink-0 opacity-70 hover:opacity-100 transition leading-none ml-0.5"
                  title="Remove"
                  aria-label={`Remove ${a.name}`}
                >✕</button>
              </div>
            )
          })}
        </div>
      )}

      {/* Attachment error notice — auto-dismisses after 4 s */}
      {attachError && (
        <div
          role="alert"
          aria-live="polite"
          className="flex items-center gap-1.5 px-1 text-[11px] text-red-600"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{attachError}</span>
        </div>
      )}

      {/* Textarea row */}
      <div className="flex items-end gap-1.5">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          title={`Attach files (images, PDFs, videos, Word docs) — max ${MAX_ATTACHMENTS} files, up to ${MAX_TOTAL_SIZE_MB}MB total${
            attachments.length > 0 ? ` (${attachments.length}/${MAX_ATTACHMENTS} attached)` : ''
          }`}
          aria-label="Attach files"
          disabled={streaming || attachments.length >= MAX_ATTACHMENTS}
          className="shrink-0 w-11 h-11 sm:w-8 sm:h-8 flex items-center justify-center rounded-lg text-slate-400 active:bg-slate-200 sm:hover:text-slate-700 sm:hover:bg-slate-100 transition disabled:opacity-40"
        >
          <PaperclipIcon />
        </button>

        <textarea
          ref={textRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={placeholder}
          dir="auto"
          rows={1}
          autoFocus
          disabled={inputDisabled}
          className="flex-1 resize-none overflow-y-auto rounded-xl border border-slate-200 px-3 py-2.5 text-[13px] leading-[1.4] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-500/20 transition disabled:opacity-50 bg-white min-h-[44px] max-h-[112px] [unicode-bidi:plaintext] text-start"
        />

        {streaming ? (
          <button
            type="button"
            onClick={() => abortRef.current?.abort()}
            title="Stop generation"
            aria-label="Stop generation"
            className="shrink-0 w-11 h-11 sm:w-9 sm:h-9 rounded-xl flex items-center justify-center text-white transition active:scale-95 bg-rose-500 sm:hover:bg-rose-600"
          >
            <StopIcon s={15} />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => sendMessage()}
            disabled={(!input.trim() && !attachments.length) || loadingSession}
            title="Send (Enter)"
            aria-label="Send message"
            className="shrink-0 w-11 h-11 sm:w-9 sm:h-9 rounded-xl flex items-center justify-center text-white transition active:scale-95 disabled:opacity-35 disabled:pointer-events-none"
            style={{ background: TOKENS.color.primary }}
          >
            <SendIcon s={15} />
          </button>
        )}
      </div>

    </div>
  )

  // ── Header (JOB-114) ────────────────────────────────────────────────────────
  // Shared between the welcome screen (no messages yet) and the active-chat
  // view below — previously this markup lived ONLY in the active-chat return
  // block, so the welcome screen rendered with no header at all: no History,
  // no New-conversation, no Minimize, and no Close ('X') button. The reported
  // symptom ("close button only appears after opening a new or existing
  // conversation") was really "there is no header until messages.length > 0",
  // since the welcome screen is exactly the `messages.length === 0` state.
  const chatHeader = (
    <div className="flex items-center justify-between px-3 py-2 pt-[max(0.5rem,env(safe-area-inset-top))] border-b border-slate-100 bg-white flex-shrink-0 z-10">
      {/* Left: avatar + name */}
      <div className="flex items-center gap-2 min-w-0">
        <div className="w-7 h-7 rounded-full text-white text-[11px] font-bold flex items-center justify-center shrink-0"
          style={{ background: TOKENS.color.gradientIntelligence, boxShadow: TOKENS.shadow.glowAi }}>A</div>
        <p className="text-[13px] font-semibold text-slate-700 truncate">Ariel</p>
      </div>
      {/* Right: icon buttons — 44px square on mobile (touch target minimum),
          28px on desktop for alignment with the compact header */}
      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={openHistory}
          title="Conversation history"
          className={`h-11 w-11 sm:h-7 sm:w-7 flex items-center justify-center rounded-lg transition-colors
            ${showHistory ? 'text-teal-600 bg-teal-50' : 'text-slate-400 active:bg-slate-200 sm:hover:text-slate-700 sm:hover:bg-slate-100'}`}
        >
          <HistoryIcon s={14} />
        </button>
        <button
          onClick={startNewSession}
          title="New conversation"
          className="h-11 w-11 sm:h-7 sm:w-7 flex items-center justify-center rounded-lg text-slate-400 active:bg-slate-200 sm:hover:text-slate-700 sm:hover:bg-slate-100 transition-colors text-[15px] leading-none"
        >↺</button>
        {onClose && (
          <>
            {/* Minimize — hides the panel; the conversation stays intact and
                can be reopened from the floating "Ask Ariel" launcher.
                Also a natural moment to re-check the Confidence Score in
                case a background CV-ingestion task finished since the last
                per-message trigger. */}
            <button
              onClick={() => { triggerProfileRefresh(); onClose() }}
              title="Minimize"
              aria-label="Minimize Ariel"
              className="h-11 w-11 sm:h-7 sm:w-7 flex items-center justify-center rounded-lg text-slate-400 active:bg-slate-200 sm:hover:text-slate-700 sm:hover:bg-slate-100 transition-colors"
            >
              <svg width={13} height={13} viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <line x1="5" y1="19" x2="19" y2="19" />
              </svg>
            </button>
            {/* Close — also hides the panel (state preserved); reopen anytime
                via the launcher. */}
            <button
              onClick={() => { triggerProfileRefresh(); onClose() }}
              title="Close"
              aria-label="Close Ariel"
              // Persistent bg-slate-100 circle on mobile only (not
              // hover/active-only) so the close control is unambiguously
              // pinned and visible on touch devices, where :hover never
              // fires; desktop keeps its minimal icon-only compact header.
              className="h-11 w-11 sm:h-7 sm:w-7 flex items-center justify-center rounded-full sm:rounded-lg bg-slate-100 sm:bg-transparent text-slate-500 sm:text-slate-400 active:bg-slate-200 sm:hover:text-slate-700 sm:hover:bg-slate-100 transition-colors"
            >
              <svg width={13} height={13} viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </>
        )}
      </div>
    </div>
  )

  // ── Welcome screen ─────────────────────────────────────────────────────────
  if (messages.length === 0 && !loadingSession) {
    const latestSession = sessionList[0] ?? null   // list is already newest-first

    const actions: { icon: string; label: string; prompt: string }[] = [
      {
        icon:   '🗺️',
        label:  'Map my career gaps',
        prompt: "I want to map the gaps between my current experience and my target role. Let's start.",
      },
      {
        icon:   '🎤',
        label:  'Prepare for an interview',
        prompt: 'I have an interview coming up. Help me prepare.',
      },
      {
        icon:   '🔍',
        label:  'Analyze a job description',
        prompt: "I'd like to analyze a job description together. I'll paste it now.",
      },
      {
        icon:   '🛤️',
        label:  'Build my career roadmap',
        prompt: 'Help me build a realistic roadmap to my next career milestone.',
      },
    ]

    return (
      <div className="flex flex-col h-full">
        {chatHeader}

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">

          {/* Identity block */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white text-base font-bold shrink-0"
              style={{ background: TOKENS.color.gradientIntelligence, boxShadow: TOKENS.shadow.glowAi }}>A</div>
            <div>
              <p className="text-[14px] font-bold text-slate-900 leading-tight">Ariel</p>
              <p className="text-[11.5px] text-slate-400 leading-tight">Career Intelligence Agent</p>
            </div>
          </div>

          {/* Resume-recent session shortcut — shown only when history exists */}
          {latestSession && (
            <button
              onClick={() => loadSession(latestSession.session_id)}
              className="w-full flex items-center gap-3 px-3.5 py-3 rounded-xl border border-teal-200 bg-teal-50 hover:bg-teal-100 transition text-left"
            >
              <span className="text-[18px] leading-none shrink-0">💬</span>
              <div className="min-w-0">
                <p className="text-[12px] font-semibold text-teal-700 leading-tight">Continue recent conversation</p>
                <p dir="auto" className="text-[11px] text-teal-500 truncate mt-0.5">
                  {latestSession.preview || 'Pick up where you left off'}
                </p>
              </div>
              <svg className="ml-auto shrink-0 text-teal-400" width={14} height={14} viewBox="0 0 24 24"
                fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </button>
          )}

          {/* Divider label */}
          <p className="text-[10.5px] font-semibold text-slate-400 uppercase tracking-wider px-0.5">
            {latestSession ? 'Or start something new' : 'What would you like to work on?'}
          </p>

          {/* Compact suggestion pills — icon + title only, wrap to fill width.
              Kept visually secondary to the auto-focused input below. */}
          <div className="flex flex-wrap gap-1.5">
            {actions.map(a => (
              <button
                key={a.label}
                onClick={() => sendMessage(a.prompt)}
                disabled={streaming}
                className="inline-flex items-center gap-1.5 pl-2 pr-2.5 py-1.5 rounded-full border border-slate-200 bg-white text-[12px] font-medium text-slate-700 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-700 transition disabled:opacity-50"
              >
                <span className="text-[14px] leading-none shrink-0">{a.icon}</span>
                {a.label}
              </button>
            ))}
          </div>

        </div>

        {renderInputBar("Or just type to start…")}
      </div>
    )
  }

  // ── Active chat ─────────────────────────────────────────────────────────────
  // Id of the last assistant message — used for Regenerate visibility
  const lastAsstId = [...messages].reverse().find(m => m.role === 'assistant')?.id
  const lastMsgId  = messages.at(-1)?.id

  return (
    <div className="flex flex-col h-full">
      {chatHeader}

      {/* Body — relative container so the history panel can overlay it */}
      <div className="relative flex-1 min-h-0">
        {/* Message list */}
        <div ref={scrollRef} className="h-full overflow-y-auto px-4 py-4 space-y-5">
          {loadingSession ? (
            <div className="flex items-center justify-center h-32 text-slate-400">
              <SpinnerIcon s={22} />
            </div>
          ) : (
            messages.map(msg => {
              // Suppress the empty placeholder bubble during TTFB — the
              // TypingIndicator below already signals Ariel is working.
              if (streaming && msg.id === lastMsgId && msg.role === 'assistant' && msg.content === '') return null
              return <MessageBubble
                key={msg.id}
                message={msg}
                isStreaming={streaming && msg.id === lastMsgId && msg.role === 'assistant'}
                showTranslation={showingTranslation.has(msg.id)}
                isTranslating={translatingIds.has(msg.id)}
                isLatestAssistant={!streaming && msg.role === 'assistant' && msg.id === lastAsstId}
                onDelete={deleteMessage}
                onReply={handleReply}
                onPin={togglePin}
                onTranslate={handleTranslate}
                onReport={handleReport}
                onEdit={handleEdit}
                onRegenerate={handleRegenerate}
              />
            })
          )}
          {streaming && messages.at(-1)?.role === 'assistant' && messages.at(-1)?.content === '' && (
            <TypingIndicator />
          )}
          <div ref={bottomRef} />
        </div>

        {/* History slide-in panel — overlays only the message list */}
        <HistoryPanel
          isOpen={showHistory}
          onClose={() => setShowHistory(false)}
          sessions={sessionList}
          loadingList={loadingList}
          activeSessionId={sessionId}
          onSelectSession={loadSession}
          onNewSession={startNewSession}
        />
      </div>

      {renderInputBar("Type your reply… (Shift+Enter for new line)")}
    </div>
  )
}
