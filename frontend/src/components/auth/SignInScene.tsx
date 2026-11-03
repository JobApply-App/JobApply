'use client'

import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { LiveRing } from './WelcomeScene'

// ── SignInScene ──────────────────────────────────────────────────────────────
//
// Beside the login form, Ariel reports back: a short briefing that writes itself
// once, with jobs arriving, scoring and sorting best first. The product is an
// agent that keeps working while the user is away, so this is what coming back
// to it looks like. The jobs are the landing's examples, and the caption says so.
//
// The orb listens to the form: it answers each character of the email, swells
// when the form is submitted, and Ariel says so when a sign-in is refused. Only
// the email moves it, so nothing gives away the length of a password. Phones skip
// the scene, because someone there came to sign in.

const ROW = 76
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'
const EASE_MOVE = 'cubic-bezier(0.77, 0, 0.175, 1)'
const TYPE_MS = 28

const prefersReduced = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

export function SignInScene({ email, going, failed }: {
  email:  string
  /** The form was submitted, or Google is on its way. */
  going:  boolean
  /** The last attempt was refused and nothing has been retyped since. */
  failed: boolean
}) {
  const { t, dir } = useI18n()
  const L = t.landing
  const S = t.login.scene
  const flip = dir === 'rtl' ? -1 : 1

  // 0 greeting, 1 jobs arrive, 2 they score, 3 they sort, 4 the last line.
  const [beat, setBeat] = useState(0)
  useEffect(() => {
    if (prefersReduced()) { setBeat(4); return }
    const timers = [1500, 2100, 3200, 4300].map((ms, i) => setTimeout(() => setBeat(i + 1), ms))
    return () => timers.forEach(clearTimeout)
  }, [])

  const line = going ? S.going : failed ? S.failed : beat === 0 ? S.away : beat < 4 ? S.found : S.next
  const [typed, setTyped] = useState(0)
  useEffect(() => {
    if (prefersReduced()) { setTyped(line.length); return }
    setTyped(0)
    const id = setInterval(() => setTyped(n => {
      if (n >= line.length) clearInterval(id)
      return n + 1
    }), TYPE_MS)
    return () => clearInterval(id)
  }, [line])

  const orb = useRef<HTMLDivElement>(null)
  const seen = useRef(email)
  useEffect(() => {
    if (seen.current === email) return
    seen.current = email
    if (prefersReduced()) return
    orb.current?.animate(
      [{ transform: 'scale(1)' }, { transform: 'scale(1.14)' }, { transform: 'scale(1)' }],
      { duration: 260, easing: EASE_OUT },
    )
  }, [email])

  const sorted = beat >= 3
  const jobs = [
    { job: L.jobs[3], score: 74.0, rank: 2 },
    { job: L.jobs[1], score: 91.2, rank: 0 },
    { job: L.jobs[0], score: 82.4, rank: 1 },
  ]

  return (
    <div className="max-lg:hidden max-w-[460px]">
      <div role="group" aria-label={L.hero.feed_label}
        className="relative overflow-hidden rounded-[28px] p-5 shadow-floating ring-1 ring-inset ring-white/15"
        style={{ background: 'linear-gradient(135deg, #115E59 0%, #134E4A 42%, #0A1F1C 100%)' }}>
        <div aria-hidden="true" className="absolute -top-24 -end-16 h-72 w-72 rounded-full blur-3xl pointer-events-none" style={{ background: 'rgba(124,58,237,.34)' }} />
        <div aria-hidden="true" className="absolute -bottom-28 -start-16 h-72 w-72 rounded-full blur-3xl pointer-events-none" style={{ background: 'rgba(94,234,212,.24)' }} />

        <div className="relative flex items-center gap-4 h-16">
          <div ref={orb} aria-hidden="true"
            className="relative h-14 w-14 shrink-0 overflow-hidden rounded-full"
            style={{
              boxShadow: failed ? '0 0 30px rgba(244,63,94,.6)' : '0 0 34px rgba(167,139,250,.65)',
              transform: going ? 'scale(1.22)' : 'none',
              transition: `transform 420ms ${EASE_OUT}, box-shadow 300ms ${EASE_OUT}`,
            }}>
            <div className="absolute -inset-3 animate-[spin_7s_linear_infinite] motion-reduce:animate-none"
              style={{ background: 'conic-gradient(#7C3AED, #5EEAD4, #A78BFA, #0D9488, #7C3AED)', filter: 'blur(5px)' }} />
            <div className="absolute inset-0" style={{ background: 'radial-gradient(circle at 34% 28%, rgba(255,255,255,.9), rgba(255,255,255,0) 46%)' }} />
          </div>
          <div className="min-w-0">
            <p className="text-[13px] text-teal-100/75">{t.login.scene.name}</p>
            <p dir="auto" className="min-h-6 text-[17px] leading-6 font-semibold tracking-tight text-white text-start">
              {line.slice(0, typed)}
            </p>
          </div>
        </div>

        <div className="relative mt-4" style={{ height: ROW * 3 - 8 }}>
          {jobs.map(({ job, score, rank }, i) => {
            const shown = beat >= 1
            const y = (sorted ? rank : i) * ROW
            return (
              <div key={job.title} className="absolute inset-x-0 top-0"
                style={{
                  transform: `translate(${shown ? 0 : 40 * flip}px, ${y}px)${going && rank === 0 ? ' scale(1.02)' : ''}`,
                  opacity: !shown ? 0 : going && rank > 0 ? 0.4 : 1,
                  transition: `transform 720ms ${EASE_MOVE} ${beat === 1 ? i * 90 : 0}ms, opacity 320ms ${EASE_OUT} ${beat === 1 ? i * 90 : 0}ms`,
                }}>
                <div className={`h-[68px] flex items-center justify-between gap-4 rounded-[18px] bg-white px-4 shadow-elevation-2 transition-shadow duration-ja-ui ${sorted && rank === 0 ? 'ring-2 ring-teal-300' : ''}`}>
                  <div className="min-w-0">
                    <p dir="auto" className="truncate text-[15px] font-bold tracking-tight text-slate-900 text-start">{job.title}</p>
                    <p className="text-[12.5px] text-slate-500">{job.place}</p>
                  </div>
                  <LiveRing target={beat >= 2 ? score : 0} />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <p className="mt-3 px-1 text-[13px] text-slate-600">{L.hero.example}</p>

      {/* The welcome gives way before the scene does when the window is short. */}
      <div className="mt-5 px-1 [@media(max-height:689px)]:hidden">
        <p className="text-[20px] leading-snug font-semibold tracking-tight text-slate-900">{t.login.page.hero_headline}</p>
        <p className="mt-1.5 text-[15px] leading-relaxed text-slate-600">{t.login.page.hero_subline}</p>
      </div>
    </div>
  )
}
