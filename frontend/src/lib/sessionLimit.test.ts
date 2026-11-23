import { beforeEach, describe, expect, it } from 'vitest'
import {
  DRAFT_KEY, DRAFT_MAX_AGE_MS, SESSION_MAX_AGE_MS,
  isPastSessionLimit, onBeforeTimeoutSignOut, runBeforeTimeoutSignOut,
  sessionDeadlineMs, signedInAtMs, stashEditorDraft, takeEditorDraft,
} from './sessionLimit'

// A token as Supabase shapes it: header.payload.signature, base64url.
function token(payload: Record<string, unknown>): string {
  const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString('base64url')
  return `${b64({ alg: 'ES256' })}.${b64(payload)}.sig`
}

const SIGNED_IN = 1_800_000_000   // seconds

describe('sign-in time from the amr claim', () => {
  it('reads the newest authentication, not iat (a refresh moves iat)', () => {
    const t = token({ iat: SIGNED_IN + 3000, amr: [{ method: 'password', timestamp: SIGNED_IN - 50 }, { method: 'otp', timestamp: SIGNED_IN }] })
    expect(signedInAtMs(t)).toBe(SIGNED_IN * 1000)
  })

  it('has no sign-in time when amr is missing or malformed', () => {
    expect(signedInAtMs(token({ iat: SIGNED_IN }))).toBeNull()
    expect(signedInAtMs(token({ amr: [{ method: 'password' }] }))).toBeNull()
    expect(signedInAtMs('not-a-jwt')).toBeNull()
  })
})

describe('the 2-hour limit', () => {
  const t = token({ amr: [{ method: 'oauth', timestamp: SIGNED_IN }] })
  const start = SIGNED_IN * 1000

  it('ends the session exactly 2 hours after sign-in', () => {
    expect(SESSION_MAX_AGE_MS).toBe(2 * 60 * 60 * 1000)
    expect(sessionDeadlineMs(t)).toBe(start + SESSION_MAX_AGE_MS)
    expect(isPastSessionLimit(t, start + SESSION_MAX_AGE_MS - 1)).toBe(false)
    expect(isPastSessionLimit(t, start + SESSION_MAX_AGE_MS)).toBe(true)
  })

  it('treats a token with no sign-in time as expired, like the backend does', () => {
    expect(isPastSessionLimit(token({ iat: SIGNED_IN }), start)).toBe(true)
  })
})

describe('Live Editor draft kept through a timeout sign-out', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    globalThis.localStorage = {
      getItem: k => store.get(k) ?? null,
      setItem: (k, v) => { store.set(k, String(v)) },
      removeItem: k => { store.delete(k) },
      clear: () => store.clear(),
      key: i => [...store.keys()][i] ?? null,
      get length() { return store.size },
    } as Storage
  })

  const draft = { userId: 'u1', jobId: 'j1', locale: 'he', cvData: { summary: 'edited' }, savedAt: 1000 }

  it('gives the draft back to the same user on the same job, once', () => {
    stashEditorDraft(draft)
    expect(takeEditorDraft('u1', 'j1', 2000)).toEqual(draft)
    expect(takeEditorDraft('u1', 'j1', 2000)).toBeNull()
  })

  it('keeps a draft for another job of the same user', () => {
    stashEditorDraft(draft)
    expect(takeEditorDraft('u1', 'other', 2000)).toBeNull()
    expect(localStorage.getItem(DRAFT_KEY)).not.toBeNull()
  })

  it('never shows one user\'s draft to another, and deletes it', () => {
    stashEditorDraft(draft)
    expect(takeEditorDraft('u2', 'j1', 2000)).toBeNull()
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull()
  })

  it('drops a draft older than a day', () => {
    stashEditorDraft(draft)
    expect(takeEditorDraft('u1', 'j1', 1000 + DRAFT_MAX_AGE_MS + 1)).toBeNull()
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull()
  })

  it('runs every registered save, even when one throws, and stops after unregister', () => {
    const ran: string[] = []
    const off1 = onBeforeTimeoutSignOut(() => { ran.push('a'); throw new Error('boom') })
    const off2 = onBeforeTimeoutSignOut(() => { ran.push('b') })
    runBeforeTimeoutSignOut()
    off1(); off2()
    runBeforeTimeoutSignOut()
    expect(ran).toEqual(['a', 'b'])
  })
})
