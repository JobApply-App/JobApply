/**
 * "3 hours ago" / "לפני 3 שעות" in the interface language, or a short date
 * after a week. Returns null for an unparseable date.
 */
export function formatRelativeTime(iso: string | null | undefined, locale: string): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (isNaN(d.getTime())) return null
  const tag    = locale === 'he' ? 'he-IL' : 'en-US'
  const rtf    = new Intl.RelativeTimeFormat(tag, { numeric: 'always', style: 'short' })
  const diffMs = Math.max(0, Date.now() - d.getTime())
  const diffH  = Math.floor(diffMs / 3_600_000)
  const diffD  = Math.floor(diffMs / 86_400_000)
  if (diffD >= 7) return d.toLocaleDateString(tag, { month: 'short', day: 'numeric' })
  if (diffD >= 1) return rtf.format(-diffD, 'day')
  if (diffH >= 1) return rtf.format(-diffH, 'hour')
  return rtf.format(-Math.max(1, Math.floor(diffMs / 60_000)), 'minute')
}
