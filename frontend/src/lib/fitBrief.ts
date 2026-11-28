// "Ariel's analysis" in the interface language (Ron 28.11). The scorer wrote
// fit_brief once, in the language of that moment; its translation into the
// other language arrives beside it (fit_brief_translations) a few minutes
// after the user's language is known. Until then the brief shows as written.

export type BriefTranslations = Partial<Record<'he' | 'en', string>> | null | undefined

export function briefIn(locale: string, brief: string | null | undefined, translations: BriefTranslations): string | null {
  const own = (brief ?? '').trim()
  if (!own) return null
  const writtenIn = /[א-ת]/.test(own) ? 'he' : 'en'
  if (writtenIn === locale) return own
  const t = translations?.[locale as 'he' | 'en']?.trim()
  return t || own
}
