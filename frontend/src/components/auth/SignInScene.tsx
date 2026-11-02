'use client'

import { useEffect, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { LiveRing } from './WelcomeScene'

// ── SignInScene ──────────────────────────────────────────────────────────────
//
// Signing in, shown as what it is: opening your feed. The example jobs wait behind
// a sliding pane of frosted glass that follows the form, a little with each
// character of the email and all the way once a password is there. Then the
// scores count up and the jobs sort themselves best first. A wrong password
// slides the pane back.
//
// It reads how far the form has got and nothing else: having a password counts,
// its length never does, so the pane gives nothing away over someone's shoulder.
// Phones skip the scene, because someone there came to sign in.

const ROW = 78
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'
const EASE_MOVE = 'cubic-bezier(0.77, 0, 0.175, 1)'
const EASE_DOOR = 'cubic-bezier(0.32, 0.72, 0, 1)'
const VALID_EMAIL = /^\S+@\S+\.\S{2,}$/

export function SignInScene({ email, hasPassword, going, failed }: {
  email:       string
  hasPassword: boolean
  /** The form was submitted, or Google is on its way. */
  going:       boolean
  /** The last attempt was refused and nothing has been retyped since. */
  failed:      boolean
}) {
  const { t, dir } = useI18n()
  const L = t.landing
  const S = t.login.scene
  const flip = dir === 'rtl' ? -1 : 1

  // A password manager fills the fields without telling React until the first
  // click, so the pane would stay shut on a form that looks finished.
  const [autofilled, setAutofilled] = useState(false)
  useEffect(() => {
    let tries = 0
    const id = setInterval(() => {
      try {
        if (document.querySelector('#password:-webkit-autofill')) { setAutofilled(true); clearInterval(id) }
      } catch { clearInterval(id) /* a browser without the selector */ }
      if (++tries > 8) clearInterval(id)
    }, 250)
    return () => clearInterval(id)
  }, [])

  const emailOk = VALID_EMAIL.test(email.trim())
  const open = going || (!failed && (autofilled || (emailOk && hasPassword)))
  const progress = open ? 1
    : emailOk || failed ? 0.55
    : email ? 0.1 + Math.min(email.length / 24, 1) * 0.3
    : 0
  const status = going ? S.going : open ? S.open : email ? S.typing : S.closed

  // In the order they arrive, deliberately not best first, so the sort is visible.
  const jobs = [
    { job: L.jobs[3], score: 74.0, rank: 2 },
    { job: L.jobs[1], score: 91.2, rank: 0 },
    { job: L.jobs[2], score: 58.6, rank: 3 },
    { job: L.jobs[0], score: 82.4, rank: 1 },
  ]

  return (
    <div className="max-lg:hidden max-w-[460px]">
      <div role="group" aria-label={L.hero.feed_label} className="relative overflow-hidden rounded-[32px]" style={{ height: ROW * 4 + 30 }}>
        {jobs.map(({ job, score, rank }, i) => (
          <div key={job.title}
            className="absolute inset-x-5 top-5 motion-reduce:!transition-none"
            style={{
              transform: `translateY(${(open ? rank : i) * ROW}px)${going && rank === 0 ? ' scale(1.03)' : ''}`,
              opacity: going && rank > 0 ? 0.35 : 1,
              zIndex: going && rank === 0 ? 1 : 0,
              transition: `transform 720ms ${EASE_MOVE}, opacity 300ms ${EASE_OUT}`,
            }}>
            <div style={{ animationDelay: `${i * 70}ms` }}
              className="animate-ja-rise motion-reduce:animate-none h-[68px] flex items-center justify-between gap-4 rounded-[18px] bg-white px-4 shadow-elevation-2">
              <div className="min-w-0">
                <p dir="auto" className="truncate text-[15px] font-bold tracking-tight text-slate-900 text-start">{job.title}</p>
                <p className="text-[12.5px] text-slate-500">{job.place}</p>
              </div>
              <LiveRing target={open ? score : 0} />
            </div>
          </div>
        ))}

        {/* The pane. Keyed on the failure so each refused attempt shakes it again. */}
        <div aria-hidden="true" className="absolute inset-0 motion-reduce:!transition-none"
          style={{
            transform: `translateX(${progress * 104 * flip}%)`,
            opacity: progress === 1 ? 0 : 1,
            transition: `transform 640ms ${EASE_DOOR}, opacity 280ms ${EASE_OUT} ${progress === 1 ? '360ms' : '0ms'}`,
          }}>
          <div key={String(failed)}
            className={`relative h-full rounded-[32px] bg-white/40 backdrop-blur-lg ring-1 ring-inset ring-white shadow-floating [@media(prefers-reduced-transparency:reduce)]:bg-white ${failed ? 'animate-ja-shake motion-reduce:animate-none' : ''}`}
            style={{ backgroundImage: 'linear-gradient(115deg, rgba(255,255,255,.55), rgba(255,255,255,.05) 45%, rgba(255,255,255,.3))' }}>
            {/* The handle, on the edge that leads as it opens. */}
            <span className="absolute start-3 top-1/2 -translate-y-1/2 h-14 w-1 rounded-full bg-slate-900/20" />
            <span className="absolute inset-0 grid place-items-center text-ja-harbor">
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="4.5" y="11" width="15" height="9.5" rx="2.5" />
                <path d="M8 11V7.5a4 4 0 0 1 8 0V11" className="motion-reduce:!transition-none"
                  style={{ transform: emailOk ? 'translateY(-1.5px)' : 'none', transition: `transform 320ms ${EASE_OUT}` }} />
              </svg>
            </span>
          </div>
        </div>
      </div>

      <p key={status} className="mt-3 px-5 text-[15px] font-semibold tracking-tight text-slate-900 animate-ja-tab-in motion-reduce:animate-none">{status}</p>
      <p className="mt-0.5 px-5 text-[13px] text-slate-600">{L.hero.example}</p>

      {/* The welcome gives way before the scene does when the window is short. */}
      <div className="mt-6 px-5 [@media(max-height:689px)]:hidden">
        <p className="text-[20px] leading-snug font-semibold tracking-tight text-slate-900">{t.login.page.hero_headline}</p>
        <p className="mt-1.5 text-[15px] leading-relaxed text-slate-600">{t.login.page.hero_subline}</p>
      </div>
    </div>
  )
}
