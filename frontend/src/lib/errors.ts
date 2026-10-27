/**
 * Turn any error into "what happened / why / what to do" in the user's
 * language.
 *
 * The server tags every error response with a `code` (backend/core/errors.py);
 * this file maps it to the texts in locales `errors.codes`. Users used to see
 * whatever English string the raising line wrote ("Scrape Failed: RapidAPI
 * found no LinkedIn job matching ID …") or a bare "something went wrong".
 * docs/error-catalog.md is the readable table of every code.
 *
 * api.ts throws ApiError, whose `message` is already the full localised
 * text — so the many components that render `err.message` explain errors
 * without changes of their own.
 */
import { dictionaries } from '../locales'
import { ERROR_CODES, ERROR_FEATURES } from '../locales/types'
import type { Dict, ErrorCode, ErrorEntry, ErrorFeature } from '../locales/types'

export type ErrorParams = Record<string, string | number>

export interface ExplainedError extends ErrorEntry {
  code: ErrorCode
  /** title + why + action as one paragraph, for places that show a single string. */
  text: string
}

const STATUS_FALLBACK: Record<number, ErrorCode> = {
  400: 'invalid_input', 401: 'session_expired', 403: 'forbidden', 404: 'item_not_found',
  409: 'conflict', 410: 'posting_closed', 413: 'file_too_large', 415: 'unsupported_file',
  422: 'invalid_input', 429: 'rate_limited', 502: 'ai_failed', 503: 'service_unavailable',
  504: 'timeout',
}

function isErrorCode(code: unknown): code is ErrorCode {
  return typeof code === 'string' && (ERROR_CODES as readonly string[]).includes(code)
}

/** The catalog code for a server code (unknown ones fall back by HTTP status). */
export function resolveErrorCode(code: unknown, status?: number): ErrorCode {
  if (isErrorCode(code)) return code
  if (status) return STATUS_FALLBACK[status] ?? (status >= 500 ? 'server_error' : 'unknown')
  return 'unknown'
}

/** The dictionary for the page's current language (<html lang>, set by I18nContext). */
export function currentErrorDict(): Dict['errors'] {
  const lang = typeof document !== 'undefined' ? document.documentElement.lang : 'en'
  return (lang === 'he' ? dictionaries.he : dictionaries.en).errors
}

function fill(template: string, params: ErrorParams, E: Dict['errors']): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    if (key === 'feature') {
      const f = params.feature
      return typeof f === 'string' && (ERROR_FEATURES as readonly string[]).includes(f)
        ? E.features[f as ErrorFeature]
        : E.features.analysis
    }
    return params[key] !== undefined ? String(params[key]) : `{${key}}`
  })
}

export function explainError(
  code: ErrorCode, params: ErrorParams = {}, E: Dict['errors'] = currentErrorDict(),
): ExplainedError {
  const entry = E.codes[code]
  // ai_failed without a feature reads "{feature} did not finish" otherwise.
  const p = code === 'ai_failed' && !params.feature ? { ...params, feature: 'analysis' } : params
  const title  = fill(entry.title, p, E)
  const why    = fill(entry.why, p, E)
  const action = fill(entry.action, p, E)
  const end = (s: string) => (/[.!?…]$/.test(s) ? s : `${s}.`)
  return { code, title, why, action, text: `${end(title)} ${why} ${action}` }
}

/** An API failure: `message` is the localised explanation, `detail` the server's English. */
export class ApiError extends Error {
  readonly code: ErrorCode
  readonly status?: number
  readonly params: ErrorParams
  readonly detail?: string
  readonly explained: ExplainedError

  constructor(code: ErrorCode, opts: { status?: number; params?: ErrorParams; detail?: string } = {}) {
    const explained = explainError(code, opts.params)
    super(explained.text)
    this.name = 'ApiError'
    this.code = code
    this.status = opts.status
    this.params = opts.params ?? {}
    this.detail = opts.detail
    this.explained = explained
  }
}

/** Build an ApiError from a parsed error body ({detail, code, params}) and status. */
export function apiErrorFromBody(body: unknown, status?: number): ApiError {
  const b = (body && typeof body === 'object' ? body : {}) as { code?: unknown; params?: unknown; detail?: unknown }
  const params = b.params && typeof b.params === 'object' ? (b.params as ErrorParams) : {}
  const detail = typeof b.detail === 'string' ? b.detail : undefined
  if (detail) console.warn('[api error]', status, b.code, detail)
  return new ApiError(resolveErrorCode(b.code, status), { status, params, detail })
}

/** The localised explanation for anything thrown (ApiError, fetch failure, other). */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof TypeError) return explainError('network').text
  if (err instanceof DOMException && err.name === 'AbortError') return explainError('timeout').text
  return explainError('unknown').text
}
