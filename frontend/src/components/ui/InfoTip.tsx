'use client'

import { useEffect, useId, useRef, useState } from 'react'

/**
 * A small (i) that explains a term. Opens on hover, on keyboard focus, and
 * on tap (phones have no hover); Escape or a tap elsewhere closes it. The
 * text is linked to the button with aria-describedby, so screen readers
 * read it without opening anything.
 */
export function InfoTip({ text, label }: { text: string; label: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span
      ref={ref}
      className="relative inline-flex align-middle"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        aria-expanded={open}
        onClick={e => { e.stopPropagation(); setOpen(o => !o) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-slate-400 hover:text-teal-700 focus-visible:text-teal-700"
      >
        <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4M12 8h.01" strokeLinecap="round" />
        </svg>
      </button>
      <span
        id={id}
        role="tooltip"
        className={`absolute z-30 top-full mt-1.5 start-1/2 -translate-x-1/2 rtl:translate-x-1/2 w-64 rounded-lg bg-slate-900 px-3 py-2 text-[12px] font-normal normal-case tracking-normal leading-relaxed text-white shadow-lg ${open ? '' : 'sr-only'}`}
      >
        {text}
      </span>
    </span>
  )
}
