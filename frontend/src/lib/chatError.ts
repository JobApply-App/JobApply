/**
 * Error thrown by the chat stream readers. It carries the server's error
 * code (backend/core/errors.py) and HTTP status, so the UI explains the
 * failure in the user's language — what happened, why, what to do — instead
 * of the server's English text or a bare "something went wrong".
 */
import { explainError, resolveErrorCode, type ErrorParams } from './errors'

export class ChatStreamError extends Error {
  status?: number
  code?: string
  params?: ErrorParams
  constructor(message: string, status?: number, code?: string, params?: ErrorParams) {
    super(message)
    this.name = 'ChatStreamError'
    this.status = status
    this.code = code
    this.params = params
  }
}

/** Parse a non-ok chat response ({detail, code, params}) into a ChatStreamError. */
export async function chatStreamErrorFrom(res: Response): Promise<ChatStreamError> {
  const text = await res.text().catch(() => '')
  let body: { detail?: unknown; error?: unknown; code?: string; params?: ErrorParams } = {}
  try { body = JSON.parse(text) } catch { /* not JSON */ }
  const message = typeof body.detail === 'string' ? body.detail
    : typeof body.error === 'string' ? body.error : `HTTP ${res.status}`
  return new ChatStreamError(message, res.status, body.code, body.params)
}

/** The localised explanation for a chat failure. Server detail goes to the console only. */
export function chatErrorText(err: unknown): string {
  if (err) console.error('[chat] stream failed:', err)
  if (err instanceof ChatStreamError) {
    return explainError(resolveErrorCode(err.code, err.status), err.params ?? {}).text
  }
  if (err instanceof TypeError) return explainError('network').text
  return explainError('stream_interrupted').text
}
