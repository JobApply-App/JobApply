'use client'

import { useEffect, useRef } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { Logo } from '@/components/ui/Logo'

// ── CareerCard ───────────────────────────────────────────────────────────────
//
// The object signup builds: a card that starts with the user's name and fills
// in as they answer, so each step visibly adds to something they keep. It only
// ever shows what they entered, and empty places stay empty. Purely a picture of
// the form beside it, so it is hidden from screen readers.
//
// Leans toward the pointer on a spring, because decoration tied straight to the
// mouse feels mechanical. Mouse only, and still under reduced motion.

const MAX_TILT = 7
const STIFFNESS = 90
const DAMPING = 13

function Slot({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[12.5px] text-teal-100/70">{label}</p>
      <div className="mt-1 h-6 flex items-center">
        {value
          ? <p key={value} dir="auto" className="truncate text-[15px] font-semibold tracking-tight text-white text-start animate-ja-rise motion-reduce:animate-none">{value}</p>
          : <span className="block h-2 w-14 rounded-full bg-white/15" />}
      </div>
    </div>
  )
}

export function CareerCard({ name, role, home, work, scanning = false }: {
  name:      string | null
  role:      string | null
  home:      string | null
  work:      string | null
  /** The CV is being read. */
  scanning?: boolean
}) {
  const { t } = useI18n()
  const face = useRef<HTMLDivElement>(null)
  const sheen = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!window.matchMedia('(pointer: fine)').matches) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const target = { x: 0, y: 0 }
    const now = { x: 0, y: 0 }
    const speed = { x: 0, y: 0 }
    let raf = 0
    let last = 0

    const tick = (time: number) => {
      const dt = Math.min((time - last) / 1000, 1 / 30)
      last = time
      for (const axis of ['x', 'y'] as const) {
        speed[axis] += (STIFFNESS * (target[axis] - now[axis]) - DAMPING * speed[axis]) * dt
        now[axis] += speed[axis] * dt
      }
      if (face.current) face.current.style.transform = `rotateX(${-now.y * MAX_TILT}deg) rotateY(${now.x * MAX_TILT}deg)`
      if (sheen.current) sheen.current.style.transform = `translate(${now.x * 22}%, ${now.y * 22}%)`
      const settled = Math.abs(target.x - now.x) + Math.abs(target.y - now.y) + Math.abs(speed.x) + Math.abs(speed.y) < 0.002
      raf = settled ? 0 : requestAnimationFrame(tick)
    }
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      const box = face.current?.getBoundingClientRect()
      if (!box) return
      const clamp = (v: number) => Math.max(-1, Math.min(1, v))
      target.x = clamp((e.clientX - (box.left + box.width / 2)) / (window.innerWidth / 2))
      target.y = clamp((e.clientY - (box.top + box.height / 2)) / (window.innerHeight / 2))
      if (!raf) { last = performance.now(); raf = requestAnimationFrame(tick) }
    }
    window.addEventListener('pointermove', onMove, { passive: true })
    return () => {
      window.removeEventListener('pointermove', onMove)
      cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <div aria-hidden="true" className="relative w-full lg:max-w-[440px] [perspective:1200px] animate-ja-card-in motion-reduce:animate-none">
      {/* The light it throws on the canvas. */}
      <div className="absolute inset-x-8 -bottom-6 top-10 rounded-[40px] blur-3xl bg-teal-500/30" />
      <div ref={face}
        className="relative overflow-hidden rounded-[24px] lg:rounded-[28px] lg:aspect-[1.586] flex flex-col justify-between gap-5 p-5 lg:p-7 shadow-floating ring-1 ring-inset ring-white/15 [transform-style:preserve-3d] will-change-transform"
        style={{ background: 'linear-gradient(135deg, #115E59 0%, #134E4A 42%, #0A1F1C 100%)' }}>
        <div ref={sheen} className="absolute -inset-1/2 pointer-events-none"
          style={{ background: 'radial-gradient(38% 38% at 34% 30%, rgba(94,234,212,.42), transparent 70%), radial-gradient(30% 30% at 74% 72%, rgba(167,139,250,.26), transparent 70%)' }} />

        <div className="relative max-lg:hidden flex justify-between">
          <span className="rounded-lg bg-white px-2 py-1.5 shadow-elevation-1"><Logo size={20} /></span>
        </div>

        <div className="relative min-w-0">
          <div className="h-9 lg:h-11 flex items-center">
            {name
              ? <p dir="auto" className="truncate text-[26px] lg:text-[32px] font-bold tracking-[-0.03em] text-white text-start">{name}</p>
              : <span className="block h-3 w-40 rounded-full bg-white/15" />}
          </div>
          <div className="mt-3 lg:mt-4 grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)] gap-3">
            <Slot label={t.onboarding.card.role} value={role} />
            <Slot label={t.onboarding.card.home} value={home} />
            <Slot label={t.onboarding.about.work_label} value={work} />
          </div>
        </div>

        {scanning && (
          <div className="absolute inset-0 border-b-2 border-teal-300 animate-ja-sweep motion-reduce:hidden"
            style={{ background: 'linear-gradient(to bottom, transparent 55%, rgba(94,234,212,.28))' }} />
        )}
      </div>
    </div>
  )
}
