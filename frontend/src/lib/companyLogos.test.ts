import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cachedLogo, requestLogo, resetCompanyLogos } from './companyLogos'

describe('company logos', () => {
  beforeEach(() => { resetCompanyLogos(); vi.useFakeTimers() })

  it('asks once for every name requested together, and remembers the answers', async () => {
    const fetcher = vi.fn(async (names: string[]): Promise<Record<string, string>> => (names.includes('Wix') ? { Wix: 'https://media.licdn.com/wix' } : {}))
    const got: Record<string, string | null> = {}
    requestLogo('Wix', u => { got.Wix = u }, fetcher)
    requestLogo('Gong', u => { got.Gong = u }, fetcher)
    requestLogo('Wix', () => {}, fetcher)
    await vi.runAllTimersAsync()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][0]).toEqual(['Wix', 'Gong'])
    expect(got).toEqual({ Wix: 'https://media.licdn.com/wix', Gong: null })
    expect(cachedLogo('Gong')).toBeNull()

    requestLogo('Wix', u => { got.again = u }, fetcher)
    expect(got.again).toBe('https://media.licdn.com/wix')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('falls back to no logo when the lookup fails', async () => {
    let got: string | null | undefined
    requestLogo('Gong', u => { got = u }, async () => { throw new Error('down') })
    await vi.runAllTimersAsync()
    expect(got).toBeNull()
  })
})
