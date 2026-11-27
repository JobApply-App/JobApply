// The home page's morning brief (design direction 1, Ron 27.11): what the
// night's search found, said in one sentence, and three steps for today.
// Pure functions so the wording rules and the "done today" record can be
// tested without rendering.

import type { ApiFeedJob } from './apiTypes'

/** A job worth the user's time: the top score band (85 and up). */
export const STRONG_SCORE = 85

export function strongCount(jobs: Pick<ApiFeedJob, 'match_score'>[]): number {
  return jobs.filter(j => j.match_score >= STRONG_SCORE).length
}

/** Which headline the brief leads with. */
export type Headline = 'strong_one' | 'strong_many' | 'fresh' | 'searching'

export function headline(strong: number, fresh: number): Headline {
  if (strong === 1) return 'strong_one'
  if (strong > 1) return 'strong_many'
  if (fresh > 0) return 'fresh'
  return 'searching'
}

// ── Today's steps, ticked off once a day ──────────────────────────────────────
// A step counts as done when the user opens it. The record is per user and
// per local day, so the list starts fresh each morning. Kept in this
// browser only: it is a convenience, and losing it costs nothing.

export type StepId = 'review' | 'tailor' | 'ariel'

export function dayKey(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

const storeKey = (userId: string, day: string) => `ja.brief.done.${userId}.${day}`

export function loadDone(userId: string, day: string = dayKey()): StepId[] {
  try {
    const raw = localStorage.getItem(storeKey(userId, day))
    const ids = raw ? JSON.parse(raw) : []
    return Array.isArray(ids) ? ids.filter((x): x is StepId => x === 'review' || x === 'tailor' || x === 'ariel') : []
  } catch {
    return []
  }
}

export function markDone(userId: string, id: StepId, day: string = dayKey()): StepId[] {
  const next = Array.from(new Set([...loadDone(userId, day), id]))
  try { localStorage.setItem(storeKey(userId, day), JSON.stringify(next)) } catch { /* private mode: still ticks for this visit */ }
  return next
}
