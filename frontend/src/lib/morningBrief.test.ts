import { beforeEach, describe, expect, it } from 'vitest'
import { dayKey, headline, loadDone, markDone, strongCount } from './morningBrief'

describe('headline', () => {
  it('leads with the jobs worth the user\'s time, then new ones, then the search', () => {
    expect(strongCount([{ match_score: 91.7 }, { match_score: 85 }, { match_score: 84.9 }])).toBe(2)
    expect(headline(1, 48)).toBe('strong_one')
    expect(headline(2, 48)).toBe('strong_many')
    expect(headline(0, 3)).toBe('fresh')
    expect(headline(0, 0)).toBe('searching')
  })
})

describe('today\'s steps', () => {
  const store = new Map<string, string>()
  beforeEach(() => {
    store.clear()
    globalThis.localStorage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, v) },
    } as Storage
  })

  it('remembers a step per user and per day, so each morning starts fresh', () => {
    markDone('u1', 'review', '2026-11-27')
    markDone('u1', 'review', '2026-11-27')
    markDone('u1', 'ariel', '2026-11-27')
    expect(loadDone('u1', '2026-11-27')).toEqual(['review', 'ariel'])
    expect(loadDone('u1', '2026-11-28')).toEqual([])
    expect(loadDone('u2', '2026-11-27')).toEqual([])
  })

  it('ignores a record it cannot read', () => {
    store.set('ja.brief.done.u1.2026-11-27', '{oops')
    expect(loadDone('u1', '2026-11-27')).toEqual([])
  })

  it('uses the local date', () => {
    expect(dayKey(new Date(2026, 10, 7))).toBe('2026-11-07')
  })
})
