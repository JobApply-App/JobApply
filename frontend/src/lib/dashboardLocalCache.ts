import type { DashboardOverviewResponse } from './api'

// Instant-render, LAST-KNOWN-RESULT store for the Overview page — explicitly
// NOT a cache in the "might serve instead of a fresh request" sense. The
// backend has no server-side cache (see backend/api/routes/dashboard.py):
// every GET /api/dashboard/overview call always recomputes from the current
// committed database state. This module only lets the Overview page paint
// something instantly on mount, labeled as a prior snapshot with its own
// timestamp, while the real (always-fresh) request is in flight in the
// background. The moment that request resolves, the displayed data is
// replaced — this store is never treated as if it were the current answer.
//
// Scoped per-user by key (never a shared/global key) so a different account
// logging in on the same browser can never read a previous user's snapshot.
// AuthContext's signOut() also calls localStorage.clear() as a second,
// independent line of defense — either one alone is sufficient to prevent
// cross-user leakage; clearDashboardSnapshot() below is a third, explicit
// one called on user change even if signOut wasn't (e.g. session swap).

const KEY_PREFIX = 'jobapply.dashboardOverview.v2.'

interface StoredSnapshot {
  data:    DashboardOverviewResponse
  savedAt: string   // ISO-8601 — when THIS snapshot was captured, not "now"
}

function keyFor(userId: string): string {
  return `${KEY_PREFIX}${userId}`
}

export interface DashboardSnapshot {
  data:    DashboardOverviewResponse
  savedAt: string
}

/** The last successful response this user saw, or null if none exists yet
 *  (first-ever visit, cleared on logout, or a different user's browser). */
export function getLastKnownDashboardSnapshot(userId: string): DashboardSnapshot | null {
  if (!userId) return null
  try {
    const raw = localStorage.getItem(keyFor(userId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredSnapshot
    if (!parsed || typeof parsed.savedAt !== 'string' || !parsed.data) return null
    return parsed
  } catch {
    // Malformed JSON, localStorage unavailable (private browsing / SSR) — a
    // miss is always a safe fallback, never a hard failure.
    return null
  }
}

export function saveDashboardSnapshot(userId: string, data: DashboardOverviewResponse): void {
  if (!userId) return
  try {
    const snapshot: StoredSnapshot = { data, savedAt: new Date().toISOString() }
    localStorage.setItem(keyFor(userId), JSON.stringify(snapshot))
  } catch {
    // Quota exceeded / storage disabled — instant-render is a nice-to-have,
    // never worth surfacing an error for.
  }
}

/** Explicit purge for this one user's snapshot — call on logout and on user
 *  change, in addition to (not instead of) AuthContext's localStorage.clear(). */
export function clearDashboardSnapshot(userId: string): void {
  if (!userId) return
  try {
    localStorage.removeItem(keyFor(userId))
  } catch {
    // Nothing to do if storage is unavailable — there's nothing to clear.
  }
}
