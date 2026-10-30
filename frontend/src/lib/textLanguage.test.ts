import { describe, expect, it } from 'vitest'
import { dominantLanguage } from './textLanguage'

describe('dominantLanguage', () => {
  it('reads an English posting as English', () => {
    expect(dominantLanguage('We are looking for a Technical Implementation Specialist to onboard B2B customers and own UAT.')).toBe('en')
  })
  it('reads a Hebrew posting with English tool names as Hebrew', () => {
    expect(dominantLanguage('דרוש/ה מנהל/ת לקוחות עם ניסיון ב-Salesforce ו-Jira, ניהול תיק לקוחות B2B ועבודה מול צוותי פיתוח ומוצר בחברת הייטק')).toBe('he')
  })
  it('reads an English posting with Hebrew boilerplate lines as English', () => {
    const jd = [
      'About the role: Extreme is looking for a Business Systems & Product Manager to own our CRM and billing systems,',
      'drive requirements with Finance and Sales, run UAT, and manage integrations with Salesforce and NetSuite.',
      'Requirements: 5+ years in business systems or product management in a B2B SaaS company. SQL is an advantage.',
      'המשרה מיועדת לנשים ולגברים כאחד',
    ].join('\n')
    expect(dominantLanguage(jd)).toBe('en')
  })
  it('does not guess from too little text', () => {
    expect(dominantLanguage('Jira')).toBeNull()
    expect(dominantLanguage(null)).toBeNull()
  })
})
