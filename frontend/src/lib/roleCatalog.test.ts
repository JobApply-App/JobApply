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
