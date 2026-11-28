import { describe, expect, it } from 'vitest'
import { briefIn } from './fitBrief'

describe('briefIn', () => {
  it('shows a brief already in the interface language as written', () => {
    expect(briefIn('en', 'Strong B2B fit.', { he: 'התאמה חזקה.' })).toBe('Strong B2B fit.')
    expect(briefIn('he', 'התאמה חזקה ל-SaaS.', { en: 'Strong SaaS fit.' })).toBe('התאמה חזקה ל-SaaS.')
  })
  it('shows the translation when the brief is in the other language', () => {
    expect(briefIn('en', 'חוזק: ניסיון B2B עמוק.', { en: 'Strength: deep B2B experience.' })).toBe('Strength: deep B2B experience.')
    expect(briefIn('he', 'Strong fit.', { he: 'התאמה חזקה.' })).toBe('התאמה חזקה.')
  })
  it('falls back to the brief as written until a translation exists', () => {
    expect(briefIn('en', 'חוזק: ניסיון.', null)).toBe('חוזק: ניסיון.')
    expect(briefIn('en', 'חוזק: ניסיון.', { en: '  ' })).toBe('חוזק: ניסיון.')
  })
  it('has nothing to show for an empty brief', () => {
    expect(briefIn('en', '  ', { en: 'x' })).toBeNull()
    expect(briefIn('he', null, null)).toBeNull()
  })
})
