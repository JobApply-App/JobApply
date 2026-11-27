'use client'
// Shared motion helpers for the redesigned screens (the morning brief, the
// focus view on Matches). Both respect reduced motion: the OS setting and
// the accessibility menu's "no animation" switch.

import { useEffect, useRef, useState } from 'react'

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReduced(mq.matches || document.documentElement.classList.contains('a11y-no-animation'))
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])
  return reduced
}

/**
 * Counts from the last shown value up to `target`, easing out. `decimals`
 * keeps one-decimal scores exact (the global rule for scores).
 */
export function useCountUp(target: number | null, reduced: boolean, ms = 1100, decimals = 0): number | null {
  const [shown, setShown] = useState<number | null>(null)
  const from = useRef(0)
  useEffect(() => {
    if (target === null) return
    if (reduced) { setShown(target); from.current = target; return }
    const start = performance.now(), a = from.current, k = 10 ** decimals
    let raf = 0
    const step = (now: number) => {
      const p = Math.min(1, (now - start) / ms)
      const v = Math.round((a + (target - a) * (1 - Math.pow(1 - p, 4))) * k) / k
      setShown(v)
      if (p < 1) raf = requestAnimationFrame(step)
      else from.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, reduced, ms, decimals])
  return shown
}
