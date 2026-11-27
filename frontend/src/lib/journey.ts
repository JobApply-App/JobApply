// The applications journey (design direction 3, Ron 27.11): where each
// application stands, as four steps, and the next thing worth doing about it.
// Built only from what the server records: the stage and the time of the last
// change. Pure functions, so the rules can be tested without rendering.

/** The four steps of the journey, in order. */
export const STEPS = ['sent', 'screen', 'interviews', 'offer'] as const
export type Step = typeof STEPS[number]

/** The step an application stage belongs to; -1 for a closed one. */
export function stepIndex(stage: string): number {
  switch (stage.trim().toLowerCase()) {
    case 'submitted':    return 0
    case 'phone screen': return 1
    case 'technical':
    case 'interview':    return 2
    case 'offer':        return 3
    case 'rejected':     return -1
    default:             return 0
  }
}

export interface JourneyCounts { sent: number; screen: number; interviews: number; offer: number; closed: number }

/** How many applications stand at each step now. */
export function journeyCounts(items: { status: string }[]): JourneyCounts {
  const c: JourneyCounts = { sent: 0, screen: 0, interviews: 0, offer: 0, closed: 0 }
  for (const { status } of items) {
    const i = stepIndex(status)
    if (i === -1) c.closed++
    else c[STEPS[i]]++
  }
  return c
}

/**
 * The server writes "2026-11-27 14:02 UTC"; very old rows say "Today 14:32",
 * which names no day and is read as unknown.
 */
export function parseUpdated(s: string | null | undefined): Date | null {
  if (!s) return null
  const m = s.match(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) UTC$/)
  const d = new Date(m ? `${m[1]}T${m[2]}:00Z` : s)
  return isNaN(d.getTime()) ? null : d
}

/** A week without news is when a short follow-up is worth sending. */
export const FOLLOW_UP_DAYS = 7

export type NextStep = 'offer' | 'prepare' | 'follow_up' | 'waiting' | 'closed'

export function nextStep(stage: string, updated: Date | null, now: Date = new Date()): NextStep {
  const i = stepIndex(stage)
  if (i === -1) return 'closed'
  if (i === 3) return 'offer'
  if (i > 0) return 'prepare'
  const days = updated ? (now.getTime() - updated.getTime()) / 86_400_000 : 0
  return days >= FOLLOW_UP_DAYS ? 'follow_up' : 'waiting'
}
