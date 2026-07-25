import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

/**
 * Stamp every /api/* request with ngrok's skip-warning header before the
 * next.config.mjs rewrite proxies it to the BACKEND_URL tunnel.
 *
 * Without this, ngrok's free tier serves an HTML browser-warning
 * interstitial (not JSON) for any request whose User-Agent looks like a
 * browser — and the rewrite proxy forwards the original browser UA, so
 * every API call from the deployed app got the warning page instead of
 * the FastAPI response. Middleware is the one place a request header can
 * be added for ALL /api/* traffic, instead of patching each fetch() call
 * across the app.
 */
export function middleware(request: NextRequest) {
  const headers = new Headers(request.headers)
  headers.set('ngrok-skip-browser-warning', 'true')
  return NextResponse.next({ request: { headers } })
}

export const config = {
  matcher: '/api/:path*',
}
