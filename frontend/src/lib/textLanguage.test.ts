import { describe, expect, it } from 'vitest'
import { dominantLanguage } from './textLanguage'

describe('dominantLanguage', () => {
  it('reads an English posting as English', () => {
    expect(dominantLanguage('We are looking for a Technical Implementation Specialist to onboard B2B customers and own UAT.')).toBe('en')
  })
  it('reads a Hebrew posting with English tool names as Hebrew', () => {
    expect(dominantLanguage('דרוש/ה מנהל/ת לקוחות עם ניסיון ב-Salesforce ו-Jira, ניהול תיק לקוחות B2B ועבודה מול צוותי פיתוח ומוצר בחברת הייטק')).toBe('he')
  })
  it('does not guess from too little text', () => {
    expect(dominantLanguage('Jira')).toBeNull()
    expect(dominantLanguage(null)).toBeNull()
  })
})
