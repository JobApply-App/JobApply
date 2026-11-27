import { describe, expect, it } from 'vitest'
import { buildSuggestions } from './arielSuggestions'
import type { AppListItem } from './api'

const now = new Date('2026-11-27T12:00:00Z')
const app = (id: string, status: string, last_update: string): AppListItem =>
  ({ application_id: id, job_id: id, title: `T${id}`, company: `C${id}`, status, last_update, score: 0 })

describe('Ariel suggestions', () => {
  it('leads with the best open match, then the furthest process, then the longest wait', () => {
    const s = buildSuggestions(
      [
        { job_id: 'a', title: 'A', company: 'X', match_score: 91.7, status: 'ignored' },
        { job_id: 'b', title: 'B', company: 'Y', match_score: 84.2, status: 'new' },
      ],
      [
        app('1', 'phone screen', '2026-11-26 09:00 UTC'),
        app('2', 'interview', '2026-11-25 09:00 UTC'),
        app('3', 'submitted', '2026-11-18 09:00 UTC'),
        app('4', 'submitted', '2026-11-10 09:00 UTC'),
      ],
      3, now,
    )
    expect(s.map(x => x.kind)).toEqual(['cv', 'prep', 'follow', 'quick'])
    expect(s[0]).toMatchObject({ company: 'Y', score: 84.2 })
    expect(s[1]).toMatchObject({ company: 'C2', stage: 'interview' })
    expect(s[2]).toMatchObject({ company: 'C4', days: 17 })
  })

  it('suggests nothing it has no data for, and fills with the standing requests', () => {
    const s = buildSuggestions([{ job_id: 'a', title: 'A', company: 'X', match_score: 55, status: 'new' }], [app('1', 'submitted', 'Today 14:32')], 3, now)
    expect(s.map(x => x.kind)).toEqual(['quick', 'quick', 'quick'])
  })
})
