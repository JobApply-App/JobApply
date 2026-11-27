import { describe, expect, it } from 'vitest'
import { journeyCounts, nextStep, parseUpdated, stepIndex } from './journey'

describe('journey', () => {
  it('places each stage on one of four steps', () => {
    expect(['submitted', 'Phone Screen', 'technical', 'interview', 'offer', 'rejected'].map(stepIndex))
      .toEqual([0, 1, 2, 2, 3, -1])
  })

  it('counts where applications stand now', () => {
    expect(journeyCounts([{ status: 'submitted' }, { status: 'submitted' }, { status: 'technical' }, { status: 'interview' }, { status: 'rejected' }]))
      .toEqual({ sent: 2, screen: 0, interviews: 2, offer: 0, closed: 1 })
  })

  it('reads the server time and leaves the old dayless format unknown', () => {
    expect(parseUpdated('2026-11-20 09:15 UTC')?.toISOString()).toBe('2026-11-20T09:15:00.000Z')
    expect(parseUpdated('Today 14:32')).toBeNull()
    expect(parseUpdated('')).toBeNull()
  })

  it('suggests a follow-up after a quiet week, and nothing invented before', () => {
    const now = new Date('2026-11-27T12:00:00Z')
    expect(nextStep('submitted', new Date('2026-11-19T12:00:00Z'), now)).toBe('follow_up')
    expect(nextStep('submitted', new Date('2026-11-25T12:00:00Z'), now)).toBe('waiting')
    expect(nextStep('submitted', null, now)).toBe('waiting')
    expect(nextStep('interview', null, now)).toBe('prepare')
    expect(nextStep('offer', null, now)).toBe('offer')
    expect(nextStep('rejected', null, now)).toBe('closed')
  })
})
