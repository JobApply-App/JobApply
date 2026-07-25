export type { Dict } from './types'
export { en } from './en'
export { he } from './he'

import { en } from './en'
import { he } from './he'

export type Locale = 'en' | 'he'

export const dictionaries = { en, he } as const
