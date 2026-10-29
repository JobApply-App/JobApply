import { ApiError } from './errors'

/**
 * Retry a PDF request while the server answers `pdf_busy` (503).
 *
 * The backend renders one PDF at a time and refuses new renders once its
 * queue is full (backend/services/chromium_slot.py), so a burst never takes
 * the server down. That refusal is not a failure the user should see: wait
 * for the server's own estimate of the queue (`waitSeconds`, clamped to
 * 1–15 s), then try again — a few times before giving up with the error.
 */
export async function retryWhileBusy<T>(
  fn: () => Promise<T>,
  waitSeconds: () => Promise<number>,
  { attempts = 6, sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms)) } = {},
): Promise<T> {
  for (let i = 0; ; i++) {
    try {
      return await fn()
    } catch (err) {
      if (!(err instanceof ApiError) || err.code !== 'pdf_busy' || i >= attempts - 1) throw err
      const s = await waitSeconds().catch(() => 3)
      await sleep(Math.min(15, Math.max(1, s)) * 1000)
    }
  }
}

/**
 * What the wait indicator shows, from the latest queue status, the seconds
 * since that status was fetched, and how long this render has waited in all.
 * Pure, so the wording rules are testable.
 *
 * - The server's `ahead` already includes this render (it is queued or
 *   running), so what is left is `ahead` renders at the average duration,
 *   less the time since the poll. (Its `eta_seconds` is for a NEW request and
 *   would count one render too many here.)
 * - progress only moves forward and stops at 95 % until the render returns.
 */
export function waitView(
  status: { ahead: number; avg_render_seconds: number } | null,
  sincePollS: number,
  elapsedS: number,
  prevProgress: number,
): { kind: 'almost' | 'eta' | 'queue'; ahead: number; seconds: number; progress: number } {
  const remaining = status ? Math.max(0, status.ahead * status.avg_render_seconds - sincePollS) : 0
  const ahead = status ? Math.max(0, status.ahead - 1) : 0
  const total = elapsedS + Math.max(remaining, 0.5)
  const progress = Math.max(prevProgress, Math.min(0.95, elapsedS / total))
  const seconds = Math.max(1, Math.ceil(remaining))
  const kind = ahead > 0 ? 'queue' : remaining <= 1.5 ? 'almost' : 'eta'
  return { kind, ahead, seconds, progress }
}
