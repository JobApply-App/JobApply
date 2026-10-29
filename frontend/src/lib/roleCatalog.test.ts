import { describe, expect, it } from 'vitest'
import { roleLabel, searchRoles } from './roleCatalog'

const none = new Set<string>()
const ens = (q: string) => searchRoles(q, none).map(r => r.en)

describe('role search', () => {
  it('finds roles outside tech, in Hebrew and English', () => {
    expect(ens('סוכן ביטוח')).toContain('Insurance Agent')
    expect(ens('ביטוח')).toContain('Insurance Agent')
    expect(ens('פנסיוני')).toContain('Pension Advisor')
    expect(ens('insurance')).toContain('Insurance Agent')
  })

  it('matches the feminine form', () => {
    expect(ens('סוכנת')).toContain('Insurance Agent')
    expect(ens('יועצת')).toContain('Pension Advisor')
    expect(ens('מנהלת מוצר')).toContain('Product Manager')
  })

  it('skips roles already picked', () => {
    expect(searchRoles('insurance agent', new Set(['insurance agent'])).map(r => r.en)).not.toContain('Insurance Agent')
  })

  it('shows the Hebrew label for a stored English role, and custom roles as typed', () => {
    expect(roleLabel('Insurance Agent', 'he')).toBe('סוכן/ת ביטוח')
    expect(roleLabel('Insurance Agent', 'en')).toBe('Insurance Agent')
    expect(roleLabel('שמאי רכב', 'he')).toBe('שמאי רכב')
  })
})

describe('Hebrew role search tolerates how people actually type', () => {
  const top = (q: string) => searchRoles(q, new Set()).map(r => r.en)
  it.each(['מנהל מוצר', 'מנהלת מוצר', 'מנהל מוצרים', 'מנהל המוצר', 'מוצר מנהל', 'product manager', 'product manag'])(
    '%s finds Product Manager', q => {
      expect(top(q)).toContain('Product Manager')
    })
  it('every typed word must match, so a second word narrows the list', () => {
    expect(top('מנהל מוצר')).not.toContain('Finance Manager')
  })
})
