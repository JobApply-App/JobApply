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

  // Walk pages until the address is found or the list is exhausted.
  //
  // This previously fetched a single page of 1000 and answered from it. Past
  // 1000 accounts that is silently wrong in the worst direction: an existing
  // address reports as free, so the "account already exists — log in" hint
  // stops appearing and the user is pushed into a signup that Supabase then
  // rejects for a reason the form never explains. Nothing fails or logs; the
  // check just quietly stops working once the project grows.
  //
  // Short-circuiting on the first match keeps the common case at one request.
  // The page cap only exists so a bug elsewhere cannot spin here forever —
  // reaching it is logged as an error rather than answered, because "we did
  // not finish looking" is not the same claim as "it does not exist", and
  // conflating those two is the defect being fixed.
  const PER_PAGE  = 1000
  const MAX_PAGES = 50

  try {
    for (let page = 1; page <= MAX_PAGES; page++) {
      const { data, error } = await supabase.auth.admin.listUsers({ page, perPage: PER_PAGE })
      if (error) {
        console.error(`${LOG} listUsers error on page ${page}:`, error.message, '— failing open')
        return NextResponse.json({ exists: false })
      }

      if (data.users.some(u => u.email?.toLowerCase() === email)) {
        return NextResponse.json({ exists: true })
      }

      // A short page is the last page.
      if (data.users.length < PER_PAGE) {
        return NextResponse.json({ exists: false })
      }
    }

    // More accounts than this endpoint is willing to scan. Answering "false"
    // here would be the original bug with a larger threshold, so say nothing
    // definitive and make the ceiling visible instead.
    console.error(
      `${LOG} exceeded ${MAX_PAGES} pages (${MAX_PAGES * PER_PAGE}+ accounts) ` +
      'without a match — this endpoint needs a targeted lookup rather than a ' +
      'full scan. Failing open.'
    )
    return NextResponse.json({ exists: false })
  } catch {
    console.error(`${LOG} unexpected error — failing open`)
    return NextResponse.json({ exists: false })
  }
}
