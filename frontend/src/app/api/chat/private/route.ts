/**
 * POST /api/chat/private
 *
 * Authenticated Next.js proxy to the Python backend's Ariel private endpoint
 * (POST /api/chat/ariel/private).
 *
 * Responsibilities
 * ────────────────
 * 1. Verify the caller's Supabase session via the Authorization header.
 * 2. Extract user_id from the Supabase JWT (the `sub` claim).
 * 3. Forward the request body plus the verified Bearer token to FastAPI.
 * 4. Stream FastAPI's SSE response verbatim back to the browser.
 *
 * Why a proxy instead of calling FastAPI directly from the browser?
 * ─────────────────────────────────────────────────────────────────
 * • Keeps the FastAPI origin private (no CORS pre-flight, no exposed port).
 * • The Supabase JWT is re-verified by FastAPI's own deps.get_current_user,
 *   so auth is validated at two layers: here (presence check) and downstream
 *   (full JWT signature verification).
 *
 * SSE passthrough
 * ───────────────
 * FastAPI streams `data: {"chunk":"..."}\n\n` events.  We pipe the raw body
 * stream directly — no buffering — so the frontend chat UI receives each delta
 * as it arrives.  No JSON parsing happens in this file.
 *
 * Error handling
 * ──────────────
 * Network failures toward FastAPI return HTTP 502.
 * Missing / malformed auth returns HTTP 401 before hitting FastAPI.
 */

import { NextRequest, NextResponse } from 'next/server'
import { createClient }              from '@supabase/supabase-js'

const BACKEND = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

// ── Supabase admin client (server-only) ───────────────────────────────────────
// Used only to verify the session and extract user_id from the access token.
// The anon key is sufficient for getUser() — it does not require the service key.

function getSupabaseClient() {
  const url    = process.env.NEXT_PUBLIC_SUPABASE_URL      ?? ''
  const anonKey= process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ''
  if (!url || !anonKey) return null
  return createClient(url, anonKey, { auth: { persistSession: false } })
}

// ── Handler ───────────────────────────────────────────────────────────────────

export async function POST(request: NextRequest): Promise<Response> {

  // ── 1. Extract and verify the Supabase session ────────────────────────────
  const authHeader = request.headers.get('Authorization') ?? ''
  const token      = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : ''

  console.log(`[chat/private] token_present=${!!token} token_prefix=${token.slice(0, 20)}...`)

  if (!token) {
    console.log('[chat/private] Rejected: no token')
    return NextResponse.json(
      { error: 'Not authenticated.' },
      { status: 401 },
    )
  }

  // Verify the JWT is still valid and extract the user_id.
  // getUser() validates the token signature against Supabase — it is NOT a
  // local decode, so it catches expired or revoked tokens reliably.
  const supabase = getSupabaseClient()
  if (supabase) {
    const { data, error } = await supabase.auth.getUser(token)
    console.log(`[chat/private] supabase.getUser → error=${error?.message ?? 'none'}  user=${data.user?.id ?? 'null'}`)
    if (error || !data.user?.id) {
      return NextResponse.json(
        { error: 'Invalid or expired session. Please log in again.' },
        { status: 401 },
      )
    }
  }

  // ── 2. Parse and validate the request body ────────────────────────────────
  let body: { message?: string; chat_history?: unknown[] }
  try {
    body = (await request.json()) as typeof body
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body.' }, { status: 400 })
  }

  if (!body.message || typeof body.message !== 'string' || !body.message.trim()) {
    console.log(`[chat/private] Rejected 422: body.message=${JSON.stringify(body.message)}  keys=${Object.keys(body)}`)
    return NextResponse.json({ error: 'message is required.' }, { status: 422 })
  }

  console.log(`[chat/private] Forwarding to FastAPI: msg_len=${body.message.trim().length}  history=${Array.isArray(body.chat_history) ? body.chat_history.length : 0}`)

  // ── 3. Forward to FastAPI ─────────────────────────────────────────────────
  let upstream: Response
  try {
    upstream = await fetch(`${BACKEND}/api/chat/ariel/private`, {
      method:  'POST',
      headers: {
        'Content-Type':  'application/json',
        // Forward the Bearer token so FastAPI's get_current_user can re-verify it
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        message:      body.message.trim(),
        chat_history: Array.isArray(body.chat_history) ? body.chat_history : [],
      }),
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'FastAPI unreachable'
    console.error('[chat/private] Backend connection failed:', msg)
    return NextResponse.json(
      { error: `Backend connection failed: ${msg}` },
      { status: 502 },
    )
  }

  if (!upstream.ok || !upstream.body) {
    // FastAPI returned a non-2xx (e.g. 401 bad token, 422 validation error).
    // Surface the error body to the client unchanged.
    const errText = await upstream.text().catch(() => upstream.statusText)
    console.error('[chat/private] FastAPI error', upstream.status, errText)
    return new Response(errText, {
      status:  upstream.status,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  // ── 4. Pipe the SSE stream directly to the browser ────────────────────────
  // We pass the upstream body stream through without buffering.  The browser
  // receives each `data: {...}` event the moment FastAPI yields it.
  return new Response(upstream.body, {
    status:  200,
    headers: {
      'Content-Type':      'text/event-stream; charset=utf-8',
      'Cache-Control':     'no-cache, no-transform',
      'Connection':        'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
