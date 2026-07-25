/**
 * Session flags for the onboarding → dashboard handoff.
 *
 * OPEN_ARIEL_FLAG is set (sessionStorage) right before the hard redirect to
 * /?tab=overview after a successful CV upload or LinkedIn import. The
 * ChatOverlay consumes it exactly once to auto-open Ariel with the welcome
 * conversation.
 */
export const OPEN_ARIEL_FLAG = 'ja_open_ariel_welcome'

export function armArielWelcome(): void {
  try { sessionStorage.setItem(OPEN_ARIEL_FLAG, '1') } catch { /* ignore */ }
}

/** Returns true (and clears the flag) if the welcome auto-open is armed. */
export function consumeArielWelcome(): boolean {
  try {
    if (sessionStorage.getItem(OPEN_ARIEL_FLAG) === '1') {
      sessionStorage.removeItem(OPEN_ARIEL_FLAG)
      return true
    }
  } catch { /* ignore */ }
  return false
}
