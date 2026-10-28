/**
 * scoreChange.ts — explain a System Confidence Score change to the user.
 *
 * A tester's score went 40.2 -> 38.2 with no explanation. It was a real
 * (since fixed) bug, but the screen gave her no way to know what had
 * changed or what to do. Every change is now compared with the last score
 * this browser showed, and the difference is explained per pillar.
 *
 * Pure functions plus a guarded localStorage snapshot. The snapshot is a
 * per-viewer convenience: when storage is unavailable the card simply shows
 * no delta, which is also what a first visit looks like.
 */

export interface IdentityAnchors {
  name:  boolean
  phone: boolean
  roles: boolean
}

export interface ScoreSnapshot {
  overall:   number
  breadth:   number
  depth:     number
  context:   number
  identity?: IdentityAnchors | null
}

export type ChangeReason =
  | 'breadth_up' | 'depth_up' | 'context_up'
  | 'breadth_down' | 'depth_down' | 'context_down'
  | 'lost_roles' | 'lost_phone' | 'lost_name'

export interface ScoreChange {
  /** 'first' when there is nothing to compare with. */
  direction: 'up' | 'down' | 'same' | 'first'
  /** One decimal, signed. 0 for 'same' and 'first'. */
  delta:     number
  reasons:   ChangeReason[]
}

/** Changes smaller than this are rounding noise, not something to show. */
const EPSILON = 0.05

const round1 = (n: number) => Math.round(n * 10) / 10

export function diffScore(prev: ScoreSnapshot | null, next: ScoreSnapshot): ScoreChange {
  if (!prev) return { direction: 'first', delta: 0, reasons: [] }
  const delta = round1(next.overall - prev.overall)
  if (Math.abs(delta) < EPSILON) return { direction: 'same', delta: 0, reasons: [] }

  const reasons: ChangeReason[] = []
  const pillars = ['breadth', 'depth', 'context'] as const
  const up = delta > 0
  for (const p of pillars) {
    const d = next[p] - prev[p]
    if (up && d >= EPSILON) reasons.push(`${p}_up` as ChangeReason)
    if (!up && d <= -EPSILON) reasons.push(`${p}_down` as ChangeReason)
  }
  // A lost identity anchor is the most specific explanation for a Context
  // drop, and the one the user can fix in a click — list it first.
  if (!up && prev.identity && next.identity) {
    const lost: ChangeReason[] = []
    if (prev.identity.roles && !next.identity.roles) lost.push('lost_roles')
    if (prev.identity.phone && !next.identity.phone) lost.push('lost_phone')
    if (prev.identity.name  && !next.identity.name)  lost.push('lost_name')
    if (lost.length) {
      return { direction: 'down', delta, reasons: [...lost, ...reasons.filter(r => r !== 'context_down')] }
    }
  }
  return { direction: up ? 'up' : 'down', delta, reasons }
}

/** Identity anchors still missing — each is a concrete way to raise the score. */
export function missingAnchors(identity: IdentityAnchors | null | undefined): (keyof IdentityAnchors)[] {
  if (!identity) return []
  return (['roles', 'phone', 'name'] as const).filter(k => !identity[k])
}

// ── Snapshot storage ─────────────────────────────────────────────────────────

const key = (userId: string) => `jobapply.scoreSnapshot.${userId}`

export function loadSnapshot(userId: string): ScoreSnapshot | null {
  try {
    const raw = window.localStorage.getItem(key(userId))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return typeof parsed?.overall === 'number' ? (parsed as ScoreSnapshot) : null
  } catch {
    return null
  }
}

export function saveSnapshot(userId: string, snap: ScoreSnapshot): void {
  try {
    window.localStorage.setItem(key(userId), JSON.stringify(snap))
  } catch {
    /* storage unavailable: the next visit just shows no delta */
  }
}
