/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep the underlying Node HTTP agent alive and raise the socket timeout
  // so the rewrite proxy doesn't drop long-running LLM responses (~25-35s).
  httpAgentOptions: {
    keepAlive: true,
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
}
export default nextConfig;
