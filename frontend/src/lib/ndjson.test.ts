import { describe, expect, it } from 'vitest'
import { NdjsonLineSplitter } from './ndjson'

describe('NdjsonLineSplitter', () => {
  it('splits multiple complete lines delivered in one chunk', () => {
    const s = new NdjsonLineSplitter()
    const lines = s.push('{"a":1}\n{"b":2}\n{"c":3}\n')
    expect(lines).toEqual(['{"a":1}', '{"b":2}', '{"c":3}'])
    expect(s.flush()).toBeNull()
  })

  it('reassembles one line split across multiple chunks', () => {
    const s = new NdjsonLineSplitter()
    expect(s.push('{"sec')).toEqual([])
    expect(s.push('tion":"overview"')).toEqual([])
    expect(s.push(',"data":{}}\n')).toEqual(['{"section":"overview","data":{}}'])
  })

  it('handles multiple lines split at arbitrary byte boundaries', () => {
    const full = '{"a":1}\n{"b":2}\n{"c":3}\n'
    // Feed one character at a time — the most adversarial possible chunking.
    const s = new NdjsonLineSplitter()
    const collected: string[] = []
    for (const ch of full) {
      collected.push(...s.push(ch))
    }
    expect(collected).toEqual(['{"a":1}', '{"b":2}', '{"c":3}'])
  })

  it('trims a trailing \\r for CRLF line endings', () => {
    const s = new NdjsonLineSplitter()
    const lines = s.push('{"a":1}\r\n{"b":2}\r\n')
    expect(lines).toEqual(['{"a":1}', '{"b":2}'])
  })

  it('handles CRLF split exactly between \\r and \\n across chunks', () => {
    const s = new NdjsonLineSplitter()
    expect(s.push('{"a":1}\r')).toEqual([])
    expect(s.push('\n{"b":2}\r\n')).toEqual(['{"a":1}', '{"b":2}'])
  })

  it('returns the final line with no trailing newline via flush()', () => {
    const s = new NdjsonLineSplitter()
    expect(s.push('{"a":1}\n{"b":2}')).toEqual(['{"a":1}'])
    expect(s.flush()).toBe('{"b":2}')
    // flush() is a one-shot drain — calling again yields nothing.
    expect(s.flush()).toBeNull()
  })

  it('flush() also trims a trailing \\r on the final unterminated line', () => {
    const s = new NdjsonLineSplitter()
    s.push('{"a":1}\r')
    // No trailing \n ever arrives (stream ended mid-line) — CRLF trimming
    // must still apply on flush.
    expect(s.flush()).toBe('{"a":1}')
  })

  it('returns null from flush() when nothing is buffered', () => {
    const s = new NdjsonLineSplitter()
    s.push('{"a":1}\n')
    expect(s.flush()).toBeNull()
  })
})
