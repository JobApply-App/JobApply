import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// api.ts's ensureFreshToken() no-ops when supabase is unconfigured (no env
// vars in this test environment), so no network/auth setup is needed here.
import { streamDashboardOverview, type DashboardStreamEvent } from './api'

/** Builds a fetch Response mock backed by a real ReadableStream, chunked
 *  exactly as the caller specifies — this is what lets tests control byte
 *  boundaries precisely (one line per chunk, one line split across chunks,
 *  character-by-character, etc). */
function makeNdjsonResponse(chunks: string[], opts?: { status?: number; contentType?: string }): Response {
  const status = opts?.status ?? 200
  const contentType = opts?.contentType ?? 'application/x-ndjson'
  const encoder = new TextEncoder()

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })

  return new Response(stream, {
    status,
    headers: { 'content-type': contentType },
  })
}

function makeJsonErrorResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('streamDashboardOverview', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function run(response: Response): Promise<{ events: DashboardStreamEvent[]; error?: Error }> {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(response)
    const events: DashboardStreamEvent[] = []
    let error: Error | undefined
    try {
      await streamDashboardOverview(e => events.push(e))
    } catch (err) {
      error = err as Error
    }
    return { events, error }
  }

  it('parses multiple NDJSON lines delivered in one chunk', async () => {
    const { events, error } = await run(makeNdjsonResponse([
      '{"section":"overview","data":{"jobs_scanned_today":1}}\n' +
      '{"section":"scraper_status","data":{"status":"ok"}}\n',
    ]))
    expect(error).toBeUndefined()
    expect(events).toHaveLength(2)
    expect(events[0].section).toBe('overview')
    expect(events[1].section).toBe('scraper_status')
  })

  it('reassembles one line split across multiple chunks', async () => {
    const { events, error } = await run(makeNdjsonResponse([
      '{"section":"overview","da',
      'ta":{"jobs_scanned_today":7}}\n',
    ]))
    expect(error).toBeUndefined()
    expect(events).toHaveLength(1)
    expect(events[0]).toEqual({ section: 'overview', data: { jobs_scanned_today: 7 } })
  })

  it('parses multiple lines split at arbitrary byte boundaries', async () => {
    const full = '{"section":"overview","data":{"a":1}}\n{"section":"trust_score","data":{"b":2}}\n'
    // One character per chunk — the most adversarial possible chunking.
    const { events, error } = await run(makeNdjsonResponse(Array.from(full)))
    expect(error).toBeUndefined()
    expect(events).toHaveLength(2)
    expect(events[0].section).toBe('overview')
    expect(events[1].section).toBe('trust_score')
  })

  it('handles CRLF line endings', async () => {
    const { events, error } = await run(makeNdjsonResponse([
      '{"section":"overview","data":{"a":1}}\r\n{"section":"scraper_status","data":{"b":2}}\r\n',
    ]))
    expect(error).toBeUndefined()
    expect(events).toHaveLength(2)
    expect(events[0].section).toBe('overview')
    expect(events[1].section).toBe('scraper_status')
  })

  it('processes a final line with no trailing newline', async () => {
    const { events, error } = await run(makeNdjsonResponse([
      '{"section":"overview","data":{"a":1}}\n{"section":"trust_score","data":{"b":2}}',
    ]))
    expect(error).toBeUndefined()
    expect(events).toHaveLength(2)
    expect(events[1].section).toBe('trust_score')
  })

  it('skips one malformed line without losing sections already parsed', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { events, error } = await run(makeNdjsonResponse([
      '{"section":"overview","data":{"a":1}}\n' +
      'not-valid-json{{{\n' +
      '{"section":"trust_score","data":{"b":2}}\n',
    ]))
    expect(error).toBeUndefined()
    // Both valid sections arrived — the malformed line in between was
    // skipped, not treated as a stream-level failure.
    expect(events).toHaveLength(2)
    expect(events[0].section).toBe('overview')
    expect(events[1].section).toBe('trust_score')
    errorSpy.mockRestore()
  })

  it('reports an HTTP non-200 JSON error response as a rejection with the parsed detail', async () => {
    const { events, error } = await run(makeJsonErrorResponse(500, { detail: 'boom: db unavailable' }))
    expect(events).toHaveLength(0)
    expect(error).toBeInstanceOf(Error)
    expect(error!.message).toContain('boom: db unavailable')
  })

  it('reports a non-200 response with a non-JSON body using a generic message', async () => {
    const response = new Response('internal error page', { status: 500, headers: { 'content-type': 'text/html' } })
    const { events, error } = await run(response)
    expect(events).toHaveLength(0)
    expect(error).toBeInstanceOf(Error)
    expect(error!.message).toContain('500')
  })

  it('rejects (rather than mis-parsing as NDJSON) a 200 response with an unexpected content-type', async () => {
    const response = new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
    const { events, error } = await run(response)
    expect(events).toHaveLength(0)
    expect(error).toBeInstanceOf(Error)
  })
})
