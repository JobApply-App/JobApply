'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from 'react'
import { ensureFreshToken, getAuthHeaders } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role:        'user' | 'assistant' | 'system'
  content:     string
  ts:          number
  isToolCall?: boolean
  toolName?:   string
  toolArgs?:   Record<string, unknown>
}

export interface ChatJobContext {
  jobTitle?: string
  company?:  string
  topic:     string
}

interface ChatState {
  // ── Ariel (authenticated) ─────────────────────────────────────────────────
  isOpen:        boolean
  jobContext:    ChatJobContext | null
  messages:      ChatMessage[]
  thinking:      boolean
  openChat:      (ctx?: ChatJobContext) => void
  closeChat:     () => void
  sendMessage:   (text: string) => void
  clearMessages: () => void
  // ── Eliya (help / support — available to all) ─────────────────────────────
  isEliyaOpen:   boolean
  openEliya:     () => void
  closeEliya:    () => void
  // ── Cross-component profile-change signal ──────────────────────────────────
  // Any chat surface that may have changed the user's Master Profile (CV
  // ingestion, a profile-editing tool call) bumps this counter. Components
  // that display profile-derived data (e.g. the System Confidence Score on
  // the Overview dashboard) can depend on it in a useEffect/useCallback to
  // know when to re-fetch, without prop-drilling across the render tree —
  // ChatOverlay/ArielChat and Overview/TrustDashboard are siblings mounted
  // in different parts of the tree, not parent/child.
  profileVersion:        number
  triggerProfileRefresh: () => void
}

// ── Context ───────────────────────────────────────────────────────────────────

const Ctx = createContext<ChatState | null>(null)

// ── Provider ──────────────────────────────────────────────────────────────────

export function ChatProvider({ children }: { children: ReactNode }) {
  const [isOpen,       setIsOpen]       = useState(false)
  const [isEliyaOpen,  setIsEliyaOpen]  = useState(false)
  const [jobContext,   setJobContext]    = useState<ChatJobContext | null>(null)
  const [messages,     setMessages]     = useState<ChatMessage[]>([])
  const [thinking,     setThinking]     = useState(false)
  const [profileVersion, setProfileVersion] = useState(0)

  const triggerProfileRefresh = useCallback(() => {
    setProfileVersion(v => v + 1)
  }, [])

  const greetedRef = useRef(false)
  const abortRef   = useRef<AbortController>(new AbortController())

  const injectContextGreeting = useCallback((ctx: ChatJobContext) => {
    const parts: string[] = []
    if (ctx.jobTitle) {
      parts.push(`**${ctx.jobTitle}**${ctx.company ? ` at ${ctx.company}` : ''}`)
    }
    parts.push(ctx.topic)
    const intro = `I'm looking at ${parts.join(' - ')}. How can you help me address this?`

    setMessages(prev => [
      ...prev,
      { role: 'system',    content: `Context loaded: ${ctx.topic}`, ts: Date.now()     },
      { role: 'user',      content: intro,                          ts: Date.now() + 1  },
      { role: 'assistant', content: buildAssistantGreeting(ctx),    ts: Date.now() + 2  },
    ])
    greetedRef.current = true
  }, [])

  const openChat = useCallback((ctx?: ChatJobContext) => {
    setIsEliyaOpen(false)   // mutual exclusion: close Eliya when opening Ariel
    if (ctx) {
      const ctxChanged =
        ctx.topic    !== jobContext?.topic ||
        ctx.jobTitle !== jobContext?.jobTitle
      if (ctxChanged) {
        greetedRef.current = false
        setMessages([])
        setJobContext(ctx)
        setTimeout(() => injectContextGreeting(ctx), 0)
      }
    }
    setIsOpen(true)
  }, [jobContext, injectContextGreeting])

  const closeChat = useCallback(() => {
    abortRef.current.abort()
    setIsOpen(false)
    setThinking(false)
  }, [])

  const openEliya  = useCallback(() => { setIsOpen(false); setIsEliyaOpen(true)  }, [])
  const closeEliya = useCallback(() => { setIsEliyaOpen(false) }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
    greetedRef.current = false
  }, [])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || thinking) return

    abortRef.current.abort()
    abortRef.current = new AbortController()
    const signal = abortRef.current.signal

    const userMsg: ChatMessage = { role: 'user', content: text.trim(), ts: Date.now() }

    let historySnapshot: ChatMessage[] = []
    setMessages(prev => {
      historySnapshot = prev
      return [...prev, userMsg]
    })
    setThinking(true)

    const apiMessages = [...historySnapshot, userMsg]
      .filter(m => (m.role === 'user' || m.role === 'assistant') && !m.isToolCall)
      .map(({ role, content }) => ({ role, content }))

    const assistantTs  = Date.now()
    let streamStarted  = false
    let accumulated    = ''

    try {
      await ensureFreshToken()
      // /api/chat/stream accepts {messages, job_context} — the correct schema for
      // this context-aware chat.  /api/chat/private (ArielChat) expects {message, chat_history}.
      const res = await fetch('/api/chat/stream', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({
          messages:    apiMessages,
          job_context: jobContext
            ? {
                topic:     jobContext.topic,
                job_title: jobContext.jobTitle ?? null,
                company:   jobContext.company  ?? null,
              }
            : null,
        }),
        signal,
      })

      if (!res.ok)    throw new Error(`${res.status} ${res.statusText}`)
      if (!res.body)  throw new Error('No response body.')

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

            let parsed: {
              chunk?: string
              error?: string
              type?:  string
              name?:  string
              input?: Record<string, unknown>
            }
            try {
              parsed = JSON.parse(payload) as typeof parsed
            } catch (_e) {
              continue
            }

            if (parsed.error) {
              throw new Error(parsed.error)
            }

            // Tool-call action card
            if (parsed.type === 'tool_call' && parsed.name) {
              setThinking(false)
              streamStarted = true
              setMessages(prev => [
                ...prev,
                {
                  role:       'assistant' as const,
                  content:    '',
                  ts:         Date.now(),
                  isToolCall: true,
                  toolName:   parsed.name!,
                  toolArgs:   parsed.input ?? {},
                },
              ])
              continue
            }

            // Text delta
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
        setMessages(prev => [
          ...prev,
          { role: 'assistant', content: '_(No response received.)_', ts: assistantTs },
        ])
      }

    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      const msg = err instanceof Error ? err.message : 'Something went wrong. Please try again.'
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: msg, ts: Date.now() },
      ])
    } finally {
      setThinking(false)
    }
  }, [thinking, jobContext])

  return (
    <Ctx.Provider value={{
      isOpen, jobContext, messages, thinking,
      openChat, closeChat, sendMessage, clearMessages,
      isEliyaOpen, openEliya, closeEliya,
      profileVersion, triggerProfileRefresh,
    }}>
      {children}
    </Ctx.Provider>
  )
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useChat(): ChatState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useChat must be used inside <ChatProvider>')
  return ctx
}

// ── Greeting helper ───────────────────────────────────────────────────────────

function buildAssistantGreeting(ctx: ChatJobContext): string {
  const roleLabel = ctx.jobTitle
    ? `the ${ctx.jobTitle}${ctx.company ? ` role at ${ctx.company}` : ''}`
    : 'this role'

  return (
    `I can see the context: **${ctx.topic}**.\n\n` +
    `Here is how I can help you with ${roleLabel}:\n\n` +
    `- **Bridge the gap** - explain how your existing experience maps to this skill\n` +
    `- **Tailor your CV** - suggest specific phrasing to highlight transferable work\n` +
    `- **Interview prep** - draft answers that address this gap confidently\n\n` +
    `What would you like to tackle first?`
  )
}
