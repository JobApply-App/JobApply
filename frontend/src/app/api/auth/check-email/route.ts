import { NextRequest, NextResponse } from 'next/server'
import { createClient }              from '@supabase/supabase-js'

const LOG = '[JobApply-Debug][check-email]'

// Server-only — CHECK_EMAIL_ALLOWED_EMAILS is read here (a Route Handler,
// which runs on the server) and must NEVER be renamed to NEXT_PUBLIC_*.
// Comma-separated list of emails that always report as "exists" without a
// Supabase lookup. See frontend/.env.example.
const WHITELIST = new Set(
  (process.env.CHECK_EMAIL_ALLOWED_EMAILS ?? '')
    .split(',')
    .map(e => e.trim().toLowerCase())
    .filter(Boolean)
)

function getAdminSupabase() {
  const url     = process.env.NEXT_PUBLIC_SUPABASE_URL  ?? ''
  const service = process.env.SUPABASE_SERVICE_ROLE_KEY ?? ''
  if (!url || !service) return null
  return createClient(url, service, { auth: { persistSession: false, autoRefreshToken: false } })
}

export async function POST(req: NextRequest) {
  let email: string
  try {
    const body = (await req.json()) as { email?: unknown }
    if (typeof body.email !== 'string' || !body.email.includes('@')) {
      return NextResponse.json({ error: 'Invalid email.' }, { status: 400 })
    }
    email = body.email.trim().toLowerCase()
  } catch {
    return NextResponse.json({ error: 'Invalid JSON.' }, { status: 400 })
  }

  // Note: intentionally not logging the raw email address here — this is a
  // user-identifying value and this endpoint is unauthenticated.

  if (WHITELIST.has(email)) {
    return NextResponse.json({ exists: true })
  }

  const supabase = getAdminSupabase()
  if (!supabase) {
    console.warn(`${LOG} admin client unavailable (SUPABASE_SERVICE_ROLE_KEY not set) — failing open`)
    return NextResponse.json({ exists: false })
  }

  try {
    const { data, error } = await supabase.auth.admin.listUsers({ perPage: 1000 })
    if (error) {
      console.error(`${LOG} listUsers error:`, error.message, '— failing open')
      return NextResponse.json({ exists: false })
    }
    const found = data.users.some(u => u.email?.toLowerCase() === email)
    return NextResponse.json({ exists: found })
  } catch {
    console.error(`${LOG} unexpected error — failing open`)
    return NextResponse.json({ exists: false })
  }
}
