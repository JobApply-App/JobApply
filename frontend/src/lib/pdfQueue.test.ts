import { describe, expect, it } from 'vitest'
import { ApiError } from './errors'
import { retryWhileBusy, waitView } from './pdfQueue'

const noSleep = { sleep: async () => {} }

describe('retryWhileBusy', () => {
  it('retries while the render queue is full, then returns the result', async () => {
    let calls = 0
    const out = await retryWhileBusy(async () => {
      if (++calls < 3) throw new ApiError('pdf_busy', { status: 503 })
      return 'pdf'
    }, async () => 2, noSleep)
    expect(out).toBe('pdf')
    expect(calls).toBe(3)
  })

  it('does not retry real failures', async () => {
    let calls = 0
    await expect(retryWhileBusy(async () => { calls++; throw new ApiError('pdf_failed') }, async () => 1, noSleep))
      .rejects.toMatchObject({ code: 'pdf_failed' })
    expect(calls).toBe(1)
  })

  it('gives up after the attempt limit', async () => {
    let calls = 0
    await expect(retryWhileBusy(async () => { calls++; throw new ApiError('pdf_busy') }, async () => 1,
      { ...noSleep, attempts: 3 })).rejects.toMatchObject({ code: 'pdf_busy' })
    expect(calls).toBe(3)
  })
})

describe('waitView', () => {
  const st = (ahead: number) => ({ ahead, avg_render_seconds: 3 })

  it('counts down this render alone: ahead includes it, so 1 x 3s, less time since the poll', () => {
    const v = waitView(st(1), 1, 1, 0)
    expect(v.kind).toBe('eta')
    expect(v.seconds).toBe(2)
  })

  it('says how many CVs are ahead when there is a queue', () => {
    const v = waitView(st(3), 0, 0.5, 0)
    expect(v.kind).toBe('queue')
    expect(v.ahead).toBe(2)
    expect(v.seconds).toBe(9)
  })

  it('switches to "almost ready" at the end and never goes backwards or past 95%', () => {
    const v = waitView(st(1), 2, 10, 0.5)
    expect(v.kind).toBe('almost')
    expect(v.progress).toBeLessThanOrEqual(0.95)
    expect(waitView(st(5), 0, 1, 0.6).progress).toBe(0.6)
  })
})
