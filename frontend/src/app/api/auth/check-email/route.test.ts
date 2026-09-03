import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// The route builds its admin client at request time from env, so the mock has
// to be in place before the module is imported. Each test re-imports with a
// fresh module registry so the mocked client is picked up.
const listUsers = vi.fn()

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({ auth: { admin: { listUsers } } }),
}))

/** One page of `n` accounts, none of which is the address under test. */
function page(n: number, prefix = 'other') {
  return {
    data: { users: Array.from({ length: n }, (_, i) => ({ email: `${prefix}${i}@example.com` })) },
    error: null,
  }
}

async function post(email: string) {
  const { POST } = await import('./route')
  const res = await POST(new Request('http://localhost/api/auth/check-email', {
    method: 'POST',
    body: JSON.stringify({ email }),
  }) as never)
  return res.json() as Promise<{ exists?: boolean; error?: string }>
}

describe('POST /api/auth/check-email', () => {
  beforeEach(() => {
    vi.resetModules()
    listUsers.mockReset()
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL', 'https://example.supabase.co')
    vi.stubEnv('SUPABASE_SERVICE_ROLE_KEY', 'service-role-test-key')
    vi.stubEnv('CHECK_EMAIL_ALLOWED_EMAILS', '')
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks() })

  it('finds an address on the first page without paging further', async () => {
    listUsers.mockResolvedValueOnce({
      data: { users: [{ email: 'Taken@Example.com' }] }, error: null,
    })
    expect(await post('taken@example.com')).toEqual({ exists: true })
    expect(listUsers).toHaveBeenCalledTimes(1)
  })

  it('reports a genuinely unused address as free', async () => {
    listUsers.mockResolvedValueOnce(page(3))
    expect(await post('nobody@example.com')).toEqual({ exists: false })
  })

  // The regression this endpoint was rewritten for: the previous version read
  // one page of 1000 and answered from it, so an account on any later page
  // reported as free and the "already registered" hint silently stopped
  // appearing once the project outgrew a single page.
  it('finds an address that sits beyond the first page', async () => {
    listUsers
      .mockResolvedValueOnce(page(1000))
      .mockResolvedValueOnce({
        data: { users: [...page(999).data.users, { email: 'late@example.com' }] },
        error: null,
      })
    expect(await post('late@example.com')).toEqual({ exists: true })
    expect(listUsers).toHaveBeenCalledTimes(2)
  })

  it('stops at a short page rather than requesting more', async () => {
    listUsers
      .mockResolvedValueOnce(page(1000))
      .mockResolvedValueOnce(page(12))
    expect(await post('nobody@example.com')).toEqual({ exists: false })
    expect(listUsers).toHaveBeenCalledTimes(2)
  })

  it('does not scan unboundedly when every page comes back full', async () => {
    listUsers.mockResolvedValue(page(1000))
    expect(await post('nobody@example.com')).toEqual({ exists: false })
    expect(listUsers).toHaveBeenCalledTimes(50)
    // Hitting the ceiling means "we stopped looking", which is not the same
    // as "it does not exist" — it has to be visible rather than silent.
    expect(console.error).toHaveBeenCalled()
  })

  it('fails open and logs when the admin call errors', async () => {
    listUsers.mockResolvedValueOnce({ data: { users: [] }, error: { message: 'boom' } })
    expect(await post('someone@example.com')).toEqual({ exists: false })
    expect(console.error).toHaveBeenCalled()
  })

  it('matches case-insensitively on the caller-supplied address', async () => {
    listUsers.mockResolvedValueOnce({
      data: { users: [{ email: 'mixed@example.com' }] }, error: null,
    })
    expect(await post('  MiXeD@Example.COM  ')).toEqual({ exists: true })
  })

  it('rejects a malformed address without calling Supabase', async () => {
    const body = await post('not-an-email')
    expect(body.error).toBeDefined()
    expect(listUsers).not.toHaveBeenCalled()
  })
})
