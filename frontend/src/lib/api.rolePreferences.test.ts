import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchRolePreferences } from './api'

// Returning users were asked for their roles again because some writers
// (Ariel's tools, older onboarding) saved only the flat title list, which the
// app read as "no roles". These pin that both shapes count as saved roles.

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
}

describe('fetchRolePreferences', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
  afterEach(() => { vi.unstubAllGlobals() })

  it('returns roles with their saved level', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(json({
      roles: [{ role: 'Insurance Agent', seniority: 'senior' }], target_titles: ['Insurance Agent'],
    }))
    expect(await fetchRolePreferences()).toEqual({ roles: [{ role: 'Insurance Agent', seniority: 'senior' }] })
  })

  it('treats a titles-only save as saved roles, not as none', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(json({ roles: [], target_titles: ['Nurse'] }))
    expect(await fetchRolePreferences()).toEqual({ roles: [{ role: 'Nurse', seniority: '' }] })
  })

  it('returns no roles when nothing was saved', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(json({ roles: [], target_titles: [] }))
    expect(await fetchRolePreferences()).toEqual({ roles: [] })
  })
})
