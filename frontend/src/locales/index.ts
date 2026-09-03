export type { Dict } from './types'
export { en } from './en'
export { he } from './he'

import { en } from './en'
import { he } from './he'

export const dictionaries = { en, he } as const

/**
 * Every language the app offers, in display order.
 *
 * This is the single place a language is declared. The header switcher and
 * the CV-language buttons both render from this list, so adding a third
 * language means adding its dictionary and one entry here — not hunting for
 * hardcoded `'en' | 'he'` pairs across components. `Locale` is derived from
 * the list rather than written out, so a new entry cannot compile until its
 * dictionary exists.
 *
 * `short` labels the compact header pill; `native` names the language in
 * itself, which is what someone who cannot read the current interface
 * language needs to see in order to escape it.
 */
export const LOCALES = [
  { code: 'en', short: 'EN', native: 'English', dir: 'ltr' },
  { code: 'he', short: 'עב', native: 'עברית',   dir: 'rtl' },
] as const satisfies readonly {
  code: keyof typeof dictionaries
  short: string
  native: string
  dir: 'ltr' | 'rtl'
}[]

export type Locale = (typeof LOCALES)[number]['code']

export const localeDir = (l: Locale): 'ltr' | 'rtl' =>
  LOCALES.find(x => x.code === l)?.dir ?? 'ltr'
