import { describe, expect, it } from 'vitest'
import { he, en } from '../locales'
import { ApiError, apiErrorFromBody, errorMessage, explainError, resolveErrorCode } from './errors'

describe('error explanations', () => {
  it('uses the server code and fills params', () => {
    const e = apiErrorFromBody({ detail: 'limit', code: 'daily_cv_limit', params: { limit: 20 } }, 429)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.code).toBe('daily_cv_limit')
    expect(e.message).toContain('20')
    expect(e.message).not.toContain('{limit}')
  })

  it('falls back to the HTTP status for an unknown or missing code', () => {
    expect(resolveErrorCode(undefined, 404)).toBe('item_not_found')
    expect(resolveErrorCode('no_such_code', 503)).toBe('service_unavailable')
    expect(resolveErrorCode(undefined, 599)).toBe('server_error')
    expect(resolveErrorCode(undefined)).toBe('unknown')
  })

  it('names the feature that failed, in each language', () => {
    expect(explainError('ai_failed', { feature: 'cv_tailoring' }, he.errors).title).toBe('התאמת קורות החיים לא הסתיים')
    expect(explainError('ai_failed', { feature: 'cv_tailoring' }, en.errors).title).toBe('Tailoring the CV did not finish')
    expect(explainError('ai_failed', {}, en.errors).title).not.toContain('{feature}')
  })

  it('never shows the server English detail', () => {
    const e = apiErrorFromBody({ detail: 'Scrape Failed: RapidAPI found no LinkedIn job', code: 'linkedin_job_not_found' }, 422)
    expect(e.message).not.toContain('RapidAPI')
    expect(e.detail).toContain('RapidAPI')
  })

  it('explains fetch failures as a connection problem', () => {
    expect(errorMessage(new TypeError('Failed to fetch'))).toBe(explainError('network').text)
  })

  it('has no unfilled placeholder in any text except known params', () => {
    for (const dict of [he, en]) {
      for (const [code, entry] of Object.entries(dict.errors.codes)) {
        for (const t of [entry.title, entry.why, entry.action]) {
          for (const m of t.match(/\{(\w+)\}/g) ?? []) {
            expect(['{limit}', '{max_mb}', '{feature}'], `${code}: ${t}`).toContain(m)
          }
        }
      }
    }
  })
})
