'use client'
// A company's logo wherever a company is named (Ron 27.11). Uses the logo the
// screen already has (All Jobs), otherwise asks the server by name (the
// LinkedIn jobs we store), then Logo.dev by name when its key is set, and
// shows the company's initials until a logo arrives or when there is none.
// The image is decoration next to the name, so it has no alt text of its own.

import { useEffect, useState } from 'react'
import { cachedLogo, requestLogo } from '@/lib/companyLogos'

// Logo.dev's publishable key: made to sit in the page, and limited in its
// dashboard to our own domains, which it checks by the referrer.
const LOGO_DEV_KEY = process.env.NEXT_PUBLIC_LOGO_DEV_KEY ?? ''

/** Logo.dev's logo for a company name, or null without a key. 404 when it has none. */
export function logoDevUrl(company: string, size: number): string | null {
  const name = company.trim()
  if (!LOGO_DEV_KEY || !name) return null
  return `https://img.logo.dev/name/${encodeURIComponent(name)}?token=${encodeURIComponent(LOGO_DEV_KEY)}`
    + `&size=${Math.min(256, Math.max(16, Math.round(size)))}&retina=true&format=png&fallback=404`
}

/** "monday.com" → "MO", "The Estée Lauder Companies" → "TE". */
export function companyInitials(company: string | null | undefined): string {
  const words = (company ?? '').trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  const s = words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)
  return s.toUpperCase()
}

export function CompanyLogo({ company, url, size = 40, radius }: {
  company: string | null | undefined
  /** A logo the screen already has; skips the lookup. */
  url?: string | null
  size?: number
  radius?: number
}) {
  const name = (company ?? '').trim()
  // undefined: still asking our server; null: it has none.
  const [found, setFound] = useState<string | null | undefined>(() => url ?? (name ? cachedLogo(name) : null))
  const [failed, setFailed] = useState(0)

  useEffect(() => {
    setFailed(0)
    if (url) { setFound(url); return }
    if (!name) { setFound(null); return }
    setFound(cachedLogo(name))
    return requestLogo(name, setFound)
  }, [name, url])

  // The logos to try, in order: ours, then Logo.dev's; an image that fails
  // to load moves on to the next.
  const candidates = found === undefined ? [] : [found, logoDevUrl(name, size)].filter((u): u is string => !!u)
  const logo = candidates[failed] ?? null

  const r = radius ?? Math.round(size * 0.28)
  const box = { width: size, height: size, borderRadius: r }

  if (!logo) {
    return (
      <span
        aria-hidden
        className="grid shrink-0 place-items-center bg-slate-100 font-extrabold text-slate-600"
        style={{ ...box, fontSize: Math.max(10, Math.round(size * 0.32)) }}
      >
        {companyInitials(name)}
      </span>
    )
  }
  const fromLogoDev = logo.startsWith('https://img.logo.dev/')
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      key={logo}
      src={logo}
      alt=""
      // LinkedIn's images need no referrer; Logo.dev checks it against our domains.
      referrerPolicy={fromLogoDev ? 'strict-origin-when-cross-origin' : 'no-referrer'}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(f => f + 1)}
      className="shrink-0 border border-slate-100 bg-white object-contain"
      style={box}
    />
  )
}
