/**
 * The 2-hour sign-in limit, browser side.
 *
 * A user must sign in again 2 hours after signing in (a security requirement,
 * 2026-11-23). Supabase would otherwise refresh the session forever, so the
 * limit is counted from the access token's `amr` claim: the time the person
 * last authenticated (password, Google, code), which a token refresh copies
 * unchanged. The backend enforces the same limit from the same claim
 * (backend/services/auth_utils.py, enforce_session_age) and answers
 * `session_time_limit`; this file signs the user out on time so they get a
 * friendly message instead of a run of failed requests.
 *
 * It also keeps the one thing a sign-out must not destroy: Live Editor text
 * the user had not saved yet. Sign-out wipes localStorage, so the editor
 * hands its draft over just before (runBeforeTimeoutSignOut), the draft is
 * kept under DRAFT_KEY through the wipe, and the editor takes it back the
 * next time the same user opens the same job.
 */

export const SESSION_MAX_AGE_MS = 2 * 60 * 60 * 1000

/** Query string the login page reads to explain why the user is there. */
export const TIMEOUT_REASON = 'session_timeout'

function decodePayload(token: string): Record<string, unknown> | null {
  const part = token.split('.')[1]
  if (!part) return null
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const json = typeof atob === 'function'
      ? atob(padded)
      : Buffer.from(padded, 'base64').toString('binary')
    const parsed: unknown = JSON.parse(json)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
}

/** When the user last signed in (ms), from the token's `amr` claim; null if absent. */
export function signedInAtMs(accessToken: string): number | null {
  const amr = decodePayload(accessToken)?.amr
  if (!Array.isArray(amr)) return null
  const times = amr
    .map(e => (e && typeof e === 'object' ? (e as { timestamp?: unknown }).timestamp : undefined))
    .filter((t): t is number => typeof t === 'number' && Number.isFinite(t))
  return times.length ? Math.max(...times) * 1000 : null
}

/**
 * The moment this session must end (ms). A token without a sign-in time is
 * already past it: the backend rejects such a token, so keeping it would only
 * produce failed requests.
 */
export function sessionDeadlineMs(accessToken: string): number {
  const at = signedInAtMs(accessToken)
  return at === null ? 0 : at + SESSION_MAX_AGE_MS
}

export function isPastSessionLimit(accessToken: string, nowMs: number = Date.now()): boolean {
  return nowMs >= sessionDeadlineMs(accessToken)
}

// ── Work to save before a timeout sign-out ───────────────────────────────────

const beforeTimeout = new Set<() => void>()

/** Register work that must run right before a timeout sign-out. Returns the unregister. */
export function onBeforeTimeoutSignOut(fn: () => void): () => void {
  beforeTimeout.add(fn)
  return () => { beforeTimeout.delete(fn) }
}

export function runBeforeTimeoutSignOut(): void {
  beforeTimeout.forEach(fn => {
    try { fn() } catch (err) { console.error('[sessionLimit] saving before sign-out failed:', err) }
  })
}

// ── Live Editor draft kept through the sign-out ──────────────────────────────

export const DRAFT_KEY = 'jobapply:timeout-draft'
/** A draft nobody came back for within a day is dropped, not kept forever. */
export const DRAFT_MAX_AGE_MS = 24 * 60 * 60 * 1000

export interface EditorDraft {
  userId: string
  jobId:  string
  locale: string
  cvData: Record<string, unknown>
  savedAt: number
}

export function stashEditorDraft(draft: EditorDraft): void {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)) } catch { /* storage full or blocked */ }
}

/**
 * The draft this user left on this job, removed from storage as it is
 * returned. A draft belonging to someone else, or older than a day, is
 * deleted; one for another job of the same user is left for that job.
 */
export function takeEditorDraft(userId: string, jobId: string, nowMs: number = Date.now()): EditorDraft | null {
  let draft: EditorDraft | null = null
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    draft = JSON.parse(raw) as EditorDraft
  } catch {
    try { localStorage.removeItem(DRAFT_KEY) } catch {}
    return null
  }
  const stale = !draft || typeof draft.savedAt !== 'number' || nowMs - draft.savedAt > DRAFT_MAX_AGE_MS
  if (stale || draft!.userId !== userId) {
    try { localStorage.removeItem(DRAFT_KEY) } catch {}
    return null
  }
  if (draft!.jobId !== jobId || !draft!.cvData || typeof draft!.cvData !== 'object') return null
  try { localStorage.removeItem(DRAFT_KEY) } catch {}
  return draft
}
