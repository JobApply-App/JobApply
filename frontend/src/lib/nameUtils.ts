/**
 * Shared user-identity helpers — display name, initials, greeting name.
 *
 * Single source of truth used by Header.tsx, page.tsx, and Overview.tsx.
 * All three previously duplicated similar but subtly different logic; this
 * module centralises the behaviour so a change here propagates everywhere.
 *
 * Priority order for display name resolution
 * ──────────────────────────────────────────
 *  1. user_metadata.full_name  (set automatically by Google / GitHub OAuth)
 *  2. user_metadata.name       (alternative metadata key used by some providers)
 *  3. email prefix             (last-resort fallback — cosmetic only; never shown
 *                               in greetings because it may contain digits/numbers)
 *
 * Updating a user's real name
 * ───────────────────────────
 * Write full_name into the user's Supabase metadata (e.g. via the
 * profile-builder interview) so tier 1 resolves it. There is intentionally no
 * hardcoded email→name override in this file — this module ships to every
 * browser, so it must never embed real names/emails. If a per-account
 * override is ever needed again, source it from an authenticated backend
 * endpoint, not from browser-bundled code.
 */

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Returns the best available display name for a user.
 *
 * Falls back to the raw email prefix as an absolute last resort so the avatar
 * always has something to show.  Components that need a human-readable greeting
 * should use `getGreetingName()` instead, which filters out email-prefix strings
 * that contain digits.
 */
export function resolveDisplayName(
  email?:    string | null,
  metadata?: Record<string, unknown> | null,
): string {
  // 1. OAuth / profile metadata (most reliable)
  const metaName = ((metadata?.full_name ?? metadata?.name) ?? '') as string
  if (metaName.trim()) return metaName.trim()

  // 2. Raw email prefix — cosmetic fallback only
  if (email) return email.split('@')[0]

  return ''
}

/**
 * Returns two-character initials from a resolved display name.
 *
 * "Jamie Smith"   → "JS"  (first letter of first word + first letter of last word)
 * "Jamie"         → "JA"  (single word — first two characters)
 * "jamiesmith98"  → "JA"  (single token — first two characters)
 * ""              → "?"   (unknown user)
 */
export function getInitials(displayName: string): string {
  const trimmed = displayName.trim()
  if (!trimmed) return '?'

  const words = trimmed.split(/\s+/).filter(Boolean)
  if (words.length >= 2) {
    // "Jamie Smith" → words[0][0]="J", words[last][0]="S" → "JS"
    return (words[0][0] + words[words.length - 1][0]).toUpperCase()
  }

  // Single word (includes email-prefix style like "jamiesmith98")
  return trimmed.slice(0, 2).toUpperCase()
}

/**
 * Returns a first name suitable for use in a greeting.
 *
 * Specifically, this function returns an empty string when the first token of
 * the display name contains a digit — which indicates an email prefix rather
 * than a real name.  Callers must render the greeting without a name in that
 * case (e.g. "Good morning" rather than "Good morning, jamiesmith98").
 *
 * "Jamie Smith"   → "Jamie"
 * "Jamie"         → "Jamie"
 * "jamiesmith98"  → ""    (contains digit — omit from greeting)
 * ""              → ""
 */
export function getGreetingName(displayName: string): string {
  if (!displayName.trim()) return ''
  const firstName = displayName.trim().split(/\s+/)[0] ?? ''
  // Reject tokens that look like email prefixes (contain any digit)
  if (/\d/.test(firstName)) return ''
  return firstName
}
