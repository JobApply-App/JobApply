/**
 * POST /api/profile/init
 *
 * Authenticated proxy to FastAPI POST /api/profile/init.
 * Called immediately after sign-up to guarantee the master_profiles row
 * exists in the database with onboarding_status = 'incomplete'.
 */

import { NextRequest, NextResponse } from 'next/server'
import { createClient }              from '@supabase/supabase-js'

const BACKEND = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

function getSupabase() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL      ?? ''
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ''
  if (!url || !key) return null
  return createClient(url, key, { auth: { persistSession: false } })
}

export async function POST(req: NextRequest) {
  const authHeader = req.headers.get('Authorization') ?? ''
  const token      = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : ''

  if (!token) {
    return NextResponse.json({ error: 'Not authenticated.' }, { status: 401 })
  }

  // Verify token
  const supabase = getSupabase()
  if (supabase) {
    const { data, error } = await supabase.auth.getUser(token)
    if (error || !data.user?.id) {
      return NextResponse.json({ error: 'Invalid session.' }, { status: 401 })
    }
  }

  let upstream: Response
  try {
    upstream = await fetch(`${BACKEND}/api/profile/init`, {
      method:  'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Backend unreachable'
    return NextResponse.json({ error: msg }, { status: 502 })
  }

  if (!upstream.ok) {
    const body = await upstream.text().catch(() => upstream.statusText)
    return new Response(body, { status: upstream.status })
  }

  return NextResponse.json({ ok: true })
}
