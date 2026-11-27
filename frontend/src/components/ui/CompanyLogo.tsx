'use client'
// A company's logo wherever a company is named (Ron 27.11). Uses the logo the
// screen already has (All Jobs), otherwise asks the server by name, and shows
// the company's initials until a logo arrives or when there is none. The
// image is decoration next to the name, so it has no alt text of its own.

import { useEffect, useState } from 'react'
import { cachedLogo, requestLogo } from '@/lib/companyLogos'

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
  const [logo, setLogo] = useState<string | null>(() => url ?? (name ? cachedLogo(name) ?? null : null))
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setFailed(false)
    if (url) { setLogo(url); return }
    if (!name) { setLogo(null); return }
    return requestLogo(name, setLogo)
  }, [name, url])

  const r = radius ?? Math.round(size * 0.28)
  const box = { width: size, height: size, borderRadius: r }

  if (!logo || failed) {
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
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={logo}
      alt=""
      referrerPolicy="no-referrer"
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className="shrink-0 border border-slate-100 bg-white object-contain"
      style={box}
    />
  )
}
