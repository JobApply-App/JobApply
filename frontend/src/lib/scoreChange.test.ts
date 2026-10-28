import { describe, expect, it } from 'vitest'
import { diffScore, missingAnchors, type ScoreSnapshot } from './scoreChange'

const base: ScoreSnapshot = {
  overall: 40.2, breadth: 32.2, depth: 0, context: 8,
  identity: { name: true, phone: false, roles: true },
}

describe('diffScore', () => {
  it('has nothing to compare on a first visit', () => {
    expect(diffScore(null, base)).toEqual({ direction: 'first', delta: 0, reasons: [] })
  })

  it('ignores rounding noise', () => {
    expect(diffScore(base, { ...base, overall: 40.22 }).direction).toBe('same')
  })

  it('explains the production drop: roles no longer counted', () => {
    // 40.2 -> 38.2, Context 8 -> 6, roles anchor gone.
    const next = { ...base, overall: 38.2, context: 6, identity: { name: true, phone: false, roles: false } }
    const change = diffScore(base, next)
    expect(change.direction).toBe('down')
    expect(change.delta).toBe(-2)
    expect(change.reasons).toEqual(['lost_roles'])
  })

  it('names the pillars that grew', () => {
    const next = { ...base, overall: 45.1, breadth: 34, depth: 3.1 }
    expect(diffScore(base, next)).toEqual({ direction: 'up', delta: 4.9, reasons: ['breadth_up', 'depth_up'] })
  })

  it('reports a depth drop (e.g. an answer flagged as too shallow)', () => {
    const next = { ...base, overall: 37.2, depth: -3 }
    expect(diffScore(base, next).reasons).toEqual(['depth_down'])
  })
})

describe('missingAnchors', () => {
  it('lists what the user can still add', () => {
    expect(missingAnchors(base.identity)).toEqual(['phone'])
    expect(missingAnchors(null)).toEqual([])
  })
})
