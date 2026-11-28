const isDev = process.env.NODE_ENV !== 'production'

// The browser only ever talks to this origin (/api/* is proxied to the
// backend) and to Supabase Auth. Read at build time like the client does.
const supabaseOrigin = (() => {
  try { return new URL(process.env.NEXT_PUBLIC_SUPABASE_URL ?? '').origin } catch { return '' }
})()

// Full Content-Security-Policy, enforced. It ran report-only first
// (2026-11-23) and a signed-in walkthrough (sign-in, dashboard, CV preview,
// PDF download, Ariel) showed no violations before it was switched on.
// A new third-party source (script, API, font, iframe) must be added here,
// or the browser blocks it.
//
// What it buys even with 'unsafe-inline': scripts can only come from this
// origin, and connect-src/img-src/form-action stop an injected script from
// sending a user's token or CV to another server. 'unsafe-inline' stays
// because Next.js app router writes inline bootstrap scripts; removing it
// needs per-request nonces from middleware, which makes every page dynamic.
// 'unsafe-eval' is dev-only (React Refresh).
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ''}`,
  "style-src 'self' 'unsafe-inline'",
  // Company logos come from LinkedIn's image CDN (stored by the scraper,
  // served by /api/all-jobs and /api/all-jobs/company-logos). Without it
  // every logo was blocked and showed as a letter. An image host cannot
  // receive a token or a CV, so this keeps what img-src protects.
  "img-src 'self' data: blob: https://media.licdn.com https://img.logo.dev",
  "font-src 'self' data:",
  `connect-src 'self' ${supabaseOrigin}`.trim(),
  // The CV preview is an <iframe> of a data: PDF; downloads use blob: URLs.
  "frame-src 'self' data: blob:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join('; ')

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep the underlying Node HTTP agent alive and raise the socket timeout
  // so the rewrite proxy doesn't drop long-running LLM responses (~25-35s).
  httpAgentOptions: {
    keepAlive: true,
  },
  eslint: {
    // `next build` runs ESLint itself. Since .eslintrc.json landed, that meant
    // every CI run linted twice and printed the same 10 warnings twice — the
    // dedicated Lint step in .github/workflows/ci.yml already gates on this
    // and fails the job on any error.
    //
    // The trade this makes: a local `npm run build` no longer surfaces lint
    // errors, so run `npm run lint` directly when that's what you want to
    // check. CI is unaffected — its Lint step runs before Build regardless.
    ignoreDuringBuilds: true,
  },
  experimental: {
    // Increase the proxy response timeout to 120s (default is ~30s in some
    // Next.js versions). Covers TailorAgent + PDF build time with headroom.
    proxyTimeout: 300_000,
  },
  async rewrites() {
    // Backend origin for the /api/* proxy below. Defaults to the local
    // FastAPI dev server (127.0.0.1:8000) so local `next dev` keeps working
    // unchanged. On Vercel, set BACKEND_URL (a plain server-side env var —
    // no NEXT_PUBLIC_ prefix needed, since next.config.mjs runs server-side)
    // to the deployed/tunneled backend origin, e.g. an ngrok URL. Without
    // this, the hardcoded 127.0.0.1 destination pointed at Vercel's own
    // serverless container in production, which Vercel's SSRF protection
    // refuses to resolve (DNS_HOSTNAME_RESOLVED_PRIVATE).
    const backendOrigin = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

    return [
      {
        // Proxy every /api/* request to the FastAPI backend.
        // This makes all fetches same-origin (no CORS) and lets the
        // frontend use relative paths regardless of which port FastAPI runs on.
        source:      '/api/:path*',
        destination: `${backendOrigin}/api/:path*`,
      },
    ]
  },

  // The backend already sends X-Frame-Options and nosniff (verified against
  // the deployed service); the frontend sent neither, so every page a user
  // actually looks at could be framed by another origin. Clickjacking on the
  // sign-in page is the case that matters: an attacker frames it invisibly
  // over their own UI and harvests the clicks.
  //
  // `frame-ancestors 'none'` is the modern control and X-Frame-Options is the
  // fallback for older agents that ignore CSP. frame-ancestors is part of
  // contentSecurityPolicy above (it only works when enforced, not report-only).
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Frame-Options',        value: 'DENY' },
          { key: 'Content-Security-Policy', value: contentSecurityPolicy },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy',        value: 'strict-origin-when-cross-origin' },
          // No camera/mic/geolocation anywhere in this product.
          { key: 'Permissions-Policy',     value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ]
  },
}
export default nextConfig;
