import { describe, expect, it } from 'vitest'
import { moveCursor, resolveIndex } from './focusQueue'

describe('focus queue', () => {
  it('follows the job, not the position, when the list reorders', () => {
    expect(resolveIndex(['b', 'a', 'c'], { id: 'a', idx: 0 })).toBe(1)
  })

  it('shows the next job when the current one leaves the list', () => {
    // 'b' was skipped: it is gone, and 'c' now sits where it was.
    expect(resolveIndex(['a', 'c'], { id: 'b', idx: 1 })).toBe(1)
    // The last one was skipped: the queue is finished.
    expect(resolveIndex(['a'], { id: 'b', idx: 1 })).toBe(1)
  })

  it('moves within the queue and stops at either end', () => {
    const ids = ['a', 'b']
    expect(moveCursor(ids, { id: 'a', idx: 0 }, 1)).toEqual({ id: 'b', idx: 1 })
    expect(moveCursor(ids, { id: 'b', idx: 1 }, 1)).toEqual({ id: null, idx: 2 })
    expect(moveCursor(ids, { id: null, idx: 2 }, 1)).toEqual({ id: null, idx: 2 })
    expect(moveCursor(ids, { id: 'a', idx: 0 }, -1)).toEqual({ id: 'a', idx: 0 })
  })
})
