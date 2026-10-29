'use client'

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const WIDTH = 256   // px — w-64
const GAP = 6       // px between the (i) and the bubble
const MARGIN = 8    // px kept clear of the viewport edge

/**
 * A small (i) that explains a term. Opens on hover, on keyboard focus, and
 * on tap (phones have no hover); Escape or a tap elsewhere closes it. The
 * text is linked to the button with aria-describedby, so screen readers
 * read it without opening anything.
 *
 * The bubble is drawn in a portal on <body> with fixed positioning. Drawn
 * inside the (i)'s own box it was cut off by any card with overflow hidden —
 * the job card's ATS Breakdown showed two lines of a five-line explanation.
 * It opens below the (i), flips above when there is no room below, and is
 * always kept inside the viewport.
 */
export function InfoTip({ text, label }: { text: string; label: string }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const id = useId()
  const anchorRef = useRef<HTMLSpanElement>(null)
  const bubbleRef = useRef<HTMLDivElement>(null)

  const place = useCallback(() => {
    const anchor = anchorRef.current?.getBoundingClientRect()
    if (!anchor) return
    const height = bubbleRef.current?.offsetHeight ?? 0
    const vw = window.innerWidth
    const vh = window.innerHeight
    const below = anchor.bottom + GAP
    const above = anchor.top - GAP - height
    // Below if it fits, else above if that fits, else the roomier side —
    // then kept inside the viewport (it may then cover the (i), which is
    // why the bubble ignores the pointer).
    let top = below + height <= vh - MARGIN ? below
      : above >= MARGIN ? above
      : vh - anchor.bottom >= anchor.top ? below : above
    top = Math.min(Math.max(MARGIN, top), Math.max(MARGIN, vh - height - MARGIN))
    const centered = anchor.left + anchor.width / 2 - WIDTH / 2
    const left = Math.min(Math.max(MARGIN, centered), Math.max(MARGIN, vw - WIDTH - MARGIN))
    setPos({ top, left })
  }, [])

  // Measure after the bubble renders (its height depends on the text), and
  // follow the (i) while the page or any scroll container moves.
  useLayoutEffect(() => {
    if (open) place()
  }, [open, place])

  useEffect(() => {
    if (!open) return
    const onDown = (e: Event) => {
      const t = e.target as Node
      if (!anchorRef.current?.contains(t) && !bubbleRef.current?.contains(t)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open, place])

  return (
    <span
      ref={anchorRef}
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
      {/* Always in the DOM for aria-describedby; the visible bubble is the portal below. */}
      <span id={id} className="sr-only">{text}</span>
      {open && typeof document !== 'undefined' && createPortal(
        <div
          ref={bubbleRef}
          role="tooltip"
          aria-hidden="true"
          className="fixed z-[1000] pointer-events-none rounded-lg bg-slate-900 px-3 py-2 text-[12px] font-normal leading-relaxed text-white shadow-lg"
          style={{
            width: WIDTH,
            maxWidth: `calc(100vw - ${MARGIN * 2}px)`,
            top: pos?.top ?? -9999,
            left: pos?.left ?? -9999,
            visibility: pos ? 'visible' : 'hidden',
          }}
        >
          {text}
        </div>,
        document.body,
      )}
    </span>
  )
}
