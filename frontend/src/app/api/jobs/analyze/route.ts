import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

/**
 * POST /api/jobs/analyze
 *
 * Explicit server-side proxy to FastAPI.
 * Using a Route Handler instead of a next.config rewrite because Next.js 14
 * rewrites do not reliably forward POST request bodies to external hosts.
 *
 * This handler:
 *   1. Receives the POST from the browser (same-origin, no CORS)
 *   2. Forwards it server-side to FastAPI (no CORS, no method loss)
 *   3. Returns FastAPI's response verbatim
 */
export async function POST(request: NextRequest) {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    return NextResponse.json(
      { detail: 'Invalid JSON body' },
      { status: 400 },
    )
  }

  // Re-attach the browser's Authorization header — without this, every
  // request reaches FastAPI with no credentials and get_current_user()
  // rejects it with 401 "Not authenticated.", regardless of session state.
  const authHeader = request.headers.get('Authorization')

  let upstream: Response
  try {
    upstream = await fetch(`${BACKEND}/api/jobs/analyze`, {
      method:  'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify(body),
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'FastAPI unreachable'
    return NextResponse.json(
      { detail: `Backend connection failed: ${msg}` },
      { status: 502 },
    )
  }

  const data = await upstream.json().catch(() => ({}))
  return NextResponse.json(data, { status: upstream.status })
}
