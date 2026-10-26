/**
 * Turn a Supabase auth error into a message for the user, in their language.
 *
 * The auth pages used to show `err.message` as-is: English text from Supabase
 * on a Hebrew page, and while the project was restricted for egress, "The
 * project owner must upgrade their plan" — an internal detail no user should
 * see. Callers now show the mapped message; the raw one goes to the console.
 */
import type { Dict } from '@/locales/types'

export type AuthErrorKind =
  | 'unavailable'
  | 'invalid_credentials'
  | 'email_not_confirmed'
  | 'already_exists'
  | 'weak_password'
  | 'rate_limited'
  | 'invalid_code'
  | 'no_account'
  | 'unknown'

export function authErrorKind(err: unknown): AuthErrorKind {
  const e = (err ?? {}) as { status?: number; code?: string; message?: string }
  const code = e.code ?? ''
  const msg = (e.message ?? '').toLowerCase()

  // 402: project restricted (quota); 5xx / no status + fetch failure: service down.
  if (e.status === 402 || (e.status ?? 0) >= 500 || msg.includes('restricted')
      || msg.includes('failed to fetch') || msg.includes('network') || msg.includes('temporarily unavailable')) {
    return 'unavailable'
  }
  if (e.status === 429 || code.startsWith('over_') || msg.includes('rate limit')) return 'rate_limited'
  if (code === 'invalid_credentials' || msg.includes('invalid login credentials')) return 'invalid_credentials'
  if (code === 'email_not_confirmed' || msg.includes('email not confirmed')) return 'email_not_confirmed'
  if (code === 'user_already_exists' || code === 'email_exists'
      || msg.includes('already registered') || msg.includes('already exists')) return 'already_exists'
  if (code === 'weak_password' || msg.includes('password should')) return 'weak_password'
  if (code === 'otp_expired' || msg.includes('token has expired') || msg.includes('invalid otp')) return 'invalid_code'
  if (code === 'otp_disabled' || code === 'user_not_found'
      || msg.includes('signups not allowed') || msg.includes('not found')) return 'no_account'
  return 'unknown'
}

/** The localized message for err, or `fallback` when the kind has no message of its own. */
export function authErrorMessage(err: unknown, C: Dict['common']['auth_errors'], fallback: string): string {
  if (err) console.error('[auth]', err)
  const kind = authErrorKind(err)
  return kind in C ? C[kind as keyof typeof C] : fallback
}
