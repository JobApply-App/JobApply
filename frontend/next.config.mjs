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
  // fallback for older agents that ignore CSP. Deliberately NOT a full CSP:
  // a default-src policy on a Next.js app needs its inline/eval allowances
  // worked out and verified page by page, and a CSP that is wrong is worse
  // than none because it breaks the app while looking like hardening. Framing
  // is the part that can be closed correctly today.
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Frame-Options',        value: 'DENY' },
          { key: 'Content-Security-Policy', value: "frame-ancestors 'none'" },
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
