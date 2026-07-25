/**
 * POST /api/chat/public
 *
 * Thin Next.js proxy to the Python backend's public Eliya endpoint
 * (POST /api/chat/public on FastAPI) — same pattern as /api/chat/private.
 *
 * Phase 5: all Eliya generation logic moved to the FastAPI backend so the
 * Phase 4 security stack applies — IP-keyed rate limiting (api/deps.py),
 * sanitize_text() on every user-supplied string, harden_system_prompt() on
 * Eliya's instructions, and strict Pydantic max_length payload caps.
 *
 * This proxy keeps only two responsibilities:
 *   1. Log the conversation to Supabase → public_chat_logs (user message
 *      awaited before forwarding; assistant reply teed from the SSE stream).
 *   2. Pipe FastAPI's SSE stream to the browser, passing status codes
 *      through unchanged — including 429 Too Many Requests, which the
 *      ChatOverlay renders as a polite "busy" notice.
 */

import { NextRequest } from 'next/server'
// eslint-disable-next-line @typescript-eslint/no-explicit-any
import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const BACKEND = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

// Mirror the backend's Pydantic caps so obviously invalid payloads are
// rejected before a cross-process hop. The backend remains authoritative.
const MAX_MESSAGE_CHARS = 1000
const MAX_HISTORY_TURNS = 10

// ── Types ─────────────────────────────────────────────────────────────────────

interface HistoryMessage {
  role:    'user' | 'assistant'
  content: string
}

interface AttachmentInput {
  base64:    string
  mediaType: string
  name:      string
}

interface RequestBody {
  session_id:   string
  message:      string
  history?:     HistoryMessage[]
  attachments?: AttachmentInput[]
}

// ── Supabase helpers ──────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyClient = SupabaseClient<any, any, any, any, any>

function getSupabaseServer(): AnyClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL      ?? ''
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ''
  if (!url.startsWith('https://') || !key.startsWith('eyJ')) return null
  return createClient(url, key)
}

function logMessage(
  supabase:     AnyClient | null,
  session_id:   string,
  role:         'user' | 'assistant',
  message_text: string,
): void {
  if (!supabase) return
  // Fire-and-forget — never await in the hot path after streaming starts
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(supabase as any)
    .from('public_chat_logs')
    .insert([{ session_id, role, message_text }])
    .then(({ error }: { error: { message: string } | null }) => {
      if (error) console.error('[public/chat] DB log failed:', error.message)
    })
    .catch((err: unknown) => {
      console.error('[public/chat] DB log threw:', err)
    })
}

// ── Handler ───────────────────────────────────────────────────────────────────

export async function POST(request: NextRequest): Promise<Response> {

  // ── 1. Validate ───────────────────────────────────────────────────────────

  let body: RequestBody
  try {
    body = (await request.json()) as RequestBody
  } catch {
    return new Response(
      JSON.stringify({ error: 'Invalid JSON body.' }),
      { status: 400, headers: { 'Content-Type': 'application/json' } },
    )
  }

  const { session_id, message, history = [], attachments = [] } = body

  if (!session_id || typeof session_id !== 'string' || !/^[0-9a-f-]{36}$/i.test(session_id)) {
    return new Response(
      JSON.stringify({ error: 'session_id must be a valid UUID.' }),
      { status: 400, headers: { 'Content-Type': 'application/json' } },
    )
  }

  if (!message || typeof message !== 'string' || !message.trim()) {
    return new Response(
      JSON.stringify({ error: 'message is required.' }),
      { status: 400, headers: { 'Content-Type': 'application/json' } },
    )
  }

  const userText = message.trim().slice(0, MAX_MESSAGE_CHARS)

  const safeHistory: HistoryMessage[] = (Array.isArray(history) ? history : [])
    .filter(m => (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
    .slice(-MAX_HISTORY_TURNS)
    .map(m => ({ role: m.role, content: m.content.slice(0, MAX_MESSAGE_CHARS) }))

  const safeAttachments: AttachmentInput[] = (Array.isArray(attachments) ? attachments : [])
    .filter(a => typeof a?.base64 === 'string' && typeof a?.mediaType === 'string')
    .slice(0, 10)
    .map(a => ({ base64: a.base64, mediaType: a.mediaType, name: typeof a.name === 'string' ? a.name.slice(0, 300) : 'file' }))

  // ── 2. Log user message (awaited — committed before the LLM call) ─────────

  const supabase = getSupabaseServer()
  await new Promise<void>(resolve => {
    if (!supabase) { resolve(); return }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(supabase as any)
      .from('public_chat_logs')
      .insert([{ session_id, role: 'user', message_text: userText }])
      .then(({ error }: { error: { message: string } | null }) => {
        if (error) console.error('[public/chat] User log failed:', error.message)
        resolve()
      })
      .catch((err: unknown) => {
        console.error('[public/chat] User log threw:', err)
        resolve()
      })
  })

  // ── 3. Forward to FastAPI ──────────────────────────────────────────────────

  let upstream: Response
  try {
    upstream = await fetch(`${BACKEND}/api/chat/public`, {
      method:  'POST',
      headers: {
        'Content-Type': 'application/json',
        // Preserve the real client IP for the backend's IP-keyed rate limiter.
        'X-Forwarded-For': request.headers.get('x-forwarded-for')
          ?? request.headers.get('x-real-ip')
          ?? '',
      },
      body: JSON.stringify({
        session_id,
        message:     userText,
        history:     safeHistory,
        attachments: safeAttachments,
      }),
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'FastAPI unreachable'
    console.error('[public/chat] Backend connection failed:', msg)
    return new Response(
      JSON.stringify({ error: 'Could not reach AI service. Please try again.' }),
      { status: 502, headers: { 'Content-Type': 'application/json' } },
    )
  }

  if (!upstream.ok || !upstream.body) {
    // Pass FastAPI's status through unchanged — a 429 here is rendered by the
    // ChatOverlay as a polite "Eliya is busy" notice, not a hard failure.
    const errText = await upstream.text().catch(() => upstream.statusText)
    console.error(`[public/chat] FastAPI error ${upstream.status}:`, errText.slice(0, 300))
    return new Response(errText || JSON.stringify({ error: 'Upstream error.' }), {
      status:  upstream.status,
      headers: {
        'Content-Type': 'application/json',
        ...(upstream.headers.get('retry-after')
          ? { 'Retry-After': upstream.headers.get('retry-after') as string }
          : {}),
      },
    })
  }

  // ── 4. Tee the SSE stream: pipe to browser + accumulate reply for logging ─

  const reader  = upstream.body.getReader()
  const decoder = new TextDecoder()

  const outStream = new ReadableStream({
    async start(controller) {
      let lineBuffer  = ''
      let accumulated = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          // Forward raw bytes untouched — parsing below is for logging only.
          controller.enqueue(value)

          lineBuffer += decoder.decode(value, { stream: true })
          const lines = lineBuffer.split('\n')
          lineBuffer  = lines.pop() ?? ''

          for (const raw of lines) {
            const line = raw.trimEnd()
            if (!line.startsWith('data:')) continue
            const payload = line.slice(5).trim()
            if (!payload || payload === '[DONE]') continue
            try {
              const evt = JSON.parse(payload) as { chunk?: string }
              if (typeof evt.chunk === 'string') accumulated += evt.chunk
            } catch { /* non-JSON data line — ignore for logging */ }
          }
        }
        logMessage(supabase, session_id, 'assistant', accumulated || '(empty)')
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error('[public/chat] Stream read error:', msg)
      } finally {
        controller.close()
        reader.releaseLock()
      }
    },
  })

  return new Response(outStream, {
    status:  200,
    headers: {
      'Content-Type':      'text/event-stream; charset=utf-8',
      'Cache-Control':     'no-cache, no-transform',
      'Connection':        'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
