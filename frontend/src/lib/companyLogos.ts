// Company logos for every screen that names a company. The screens know only
// the name; the server looks the logo up among the LinkedIn jobs it stores.
// Names asked for in the same moment go out as one request, and every answer
// (a logo or "none") is kept for the visit, so a list of fifty cards costs a
// single call and a second visit to the screen costs nothing.

import { fetchCompanyLogos } from './api'

const MAX_PER_REQUEST = 100
const known = new Map<string, string | null>()
const waiting = new Map<string, Set<(url: string | null) => void>>()
let timer: ReturnType<typeof setTimeout> | null = null

/** For tests: forget everything. */
export function resetCompanyLogos(): void {
  known.clear(); waiting.clear()
  if (timer) clearTimeout(timer)
  timer = null
}

export function cachedLogo(name: string): string | null | undefined {
  return known.get(name)
}

/** Calls `done` with the logo, or null when there is none or the lookup failed. */
export function requestLogo(name: string, done: (url: string | null) => void, fetcher = fetchCompanyLogos): () => void {
  const have = known.get(name)
  if (have !== undefined) { done(have); return () => {} }
  const set = waiting.get(name) ?? new Set()
  set.add(done)
  waiting.set(name, set)
  if (!timer) timer = setTimeout(() => flush(fetcher), 30)
  return () => { set.delete(done) }
}

async function flush(fetcher: typeof fetchCompanyLogos) {
  timer = null
  const names = Array.from(waiting.keys())
  const batches: string[][] = []
  for (let i = 0; i < names.length; i += MAX_PER_REQUEST) batches.push(names.slice(i, i + MAX_PER_REQUEST))
  await Promise.all(batches.map(async batch => {
    let logos: Record<string, string> = {}
    try { logos = await fetcher(batch) } catch { /* the initials stay */ }
    for (const name of batch) {
      const url = logos[name] ?? null
      known.set(name, url)
      waiting.get(name)?.forEach(cb => cb(url))
      waiting.delete(name)
    }
  }))
}
