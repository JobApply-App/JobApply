/**
 * The language a text is mostly written in: 'he' when at least 40% of its
 * letters are Hebrew (Hebrew postings keep English product and tool names),
 * 'en' otherwise, null when there is too little text to tell.
 * Mirrors backend/services/pdf_builder.py detect_cv_locale().
 */
export function dominantLanguage(text: string | null | undefined): 'he' | 'en' | null {
  const he = (text?.match(/[֐-׿]/g) ?? []).length
  const en = (text?.match(/[A-Za-z]/g) ?? []).length
  if (he + en < 40) return null
  return he / (he + en) >= 0.4 ? 'he' : 'en'
}
