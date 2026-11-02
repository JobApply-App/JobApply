'use client'

import { useEffect, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { getScoreBand } from '@/lib/scoreBand'
import { KycShell } from './KycShell'
import { kycPrimary, kycSub, kycTitle } from './authStyles'

// ── WelcomeScene ─────────────────────────────────────────────────────────────
//
// The first screen after signup, and the product showing itself instead of
// describing itself: a CV is read with the user's own name on it, jobs score and
// sort themselves best first, and the CV rewrites itself for the top one. Each
// chapter on the side is one act; tapping one takes over from the autoplay.
//
// Only the name is real, and the caption says so. Plays once, never loops.

const ACT_MS = [4600, 5400, 3600]
// When each act's second and third beats land, in ms from the start of the act.
const BEATS = [[700, 1700], [250, 2300], [600, 2000]]
const ROW = 82
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'
const EASE_MOVE = 'cubic-bezier(0.77, 0, 0.175, 1)'

const prefersReduced = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

function LiveRing({ target, size = 48 }: { target: number; size?: number }) {
  const [shown, setShown] = useState(0)
  const band = getScoreBand(Math.max(target, 1))
  useEffect(() => {
    if (prefersReduced()) { setShown(target); return }
    const from = shown
    const start = performance.now()
    let raf = requestAnimationFrame(function tick(now) {
      const p = Math.min((now - start) / 1100, 1)
      setShown(from + (target - from) * (1 - Math.pow(1 - p, 4)))
      if (p < 1) raf = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- starts from wherever it was interrupted
  }, [target])
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
        <circle cx="18" cy="18" r="15.9" fill="none" stroke={band.hexBg} strokeWidth="3.2" pathLength={100} />
        <circle cx="18" cy="18" r="15.9" fill="none" stroke={band.hexFg} strokeWidth="3.2" strokeLinecap="round"
          pathLength={100} strokeDasharray={`${shown} 100`} />
      </svg>
      <span className="absolute inset-0 grid place-items-center font-bold tabular-nums tracking-tight"
        style={{ color: band.key === 'moderate' ? '#B45309' : band.hexFg, fontSize: size * 0.23 }}>
        {shown.toFixed(1)}
      </span>
    </div>
  )
}

function Stage({ act, beat, name }: { act: number; beat: number; name: string | null }) {
  const { t, dir } = useI18n()
  const S = t.onboarding.showcase
  const L = t.landing
  const flip = dir === 'rtl' ? -1 : 1
  const shownName = name ?? S.name_fallback

  // Types itself in the first act; complete whenever the scene is anywhere else.
  const [typed, setTyped] = useState(0)
  useEffect(() => {
    if (act !== 0 || prefersReduced()) { setTyped(shownName.length); return }
    setTyped(0)
    const id = setInterval(() => setTyped(n => {
      if (n >= shownName.length) clearInterval(id)
      return n + 1
    }), 55)
    return () => clearInterval(id)
  }, [act, shownName])

  // In the order they arrive, deliberately not best first, so the sort is visible.
  const jobs = [
    { job: L.jobs[3], score: 74.0, rank: 2 },
    { job: L.jobs[1], score: 91.2, rank: 0 },
    { job: L.jobs[2], score: 58.6, rank: 3 },
    { job: L.jobs[0], score: 82.4, rank: 1 },
  ]
  const sorted = act === 1 && beat >= 2

  return (
    <div aria-hidden="true" className="relative w-[380px] h-[460px] shrink-0 max-lg:scale-[.5] max-lg:-translate-y-3 xl:scale-[1.12]">
      {/* The CV */}
      <div className="absolute start-[30px] top-[30px] w-[320px] h-[400px] overflow-hidden rounded-[20px] bg-white shadow-floating p-6"
        style={{
          transform: act === 0 ? 'none' : act === 1 ? 'translateY(-6px) scale(.9)' : 'translateY(44px) scale(.94)',
          opacity: act === 1 ? 0 : 1,
          transition: `transform 700ms ${EASE_MOVE}, opacity 450ms ${EASE_OUT}`,
        }}>
        <p dir="auto" className="min-h-7 truncate text-[20px] leading-7 font-bold tracking-tight text-slate-900 text-start">
          {shownName.slice(0, typed)}
          {act === 0 && beat < 1 && <span className="inline-block w-[2px] h-5 ms-0.5 align-[-3px] bg-teal-600" />}
        </p>
        <div className="mt-2 h-2 w-2/5 rounded-full bg-slate-200" />
        <div className="mt-5 h-px bg-slate-100" />

        <div className="mt-5 space-y-5">
          {S.cv_lines.map((line, i) => {
            const rewritten = act === 2 && beat >= 1
            const delay = `${i * 170}ms`
            return (
              <div key={line.mark} className="relative h-10">
                <div className="absolute inset-0 space-y-2" style={{ opacity: rewritten ? 0 : 1, transition: `opacity 260ms ${EASE_OUT} ${rewritten ? delay : '0ms'}` }}>
                  {[100, 72].map((w, j) => (
                    <div key={w} className="h-2 rounded-full bg-slate-200 origin-left rtl:origin-right"
                      style={{
                        width: `${w}%`,
                        transform: act > 0 || beat >= 1 ? 'scaleX(1)' : 'scaleX(0)',
                        transition: `transform 500ms ${EASE_OUT} ${(i * 2 + j) * 70}ms`,
                      }} />
                  ))}
                </div>
                <p className="absolute inset-0 text-[13.5px] leading-5 text-slate-700 text-start"
                  style={{
                    opacity: rewritten ? 1 : 0,
                    transform: rewritten ? 'none' : 'translateY(5px)',
                    transition: `opacity 320ms ${EASE_OUT} ${rewritten ? delay : '0ms'}, transform 320ms ${EASE_OUT} ${rewritten ? delay : '0ms'}`,
                  }}>
                  {line.before}
                  <span className="relative isolate whitespace-nowrap font-semibold text-teal-900">
                    <span className="absolute -inset-x-0.5 inset-y-0 -z-10 rounded bg-teal-100 origin-left rtl:origin-right"
                      style={{
                        transform: rewritten ? 'scaleX(1)' : 'scaleX(0)',
                        transition: `transform 420ms ${EASE_OUT} ${rewritten ? `${i * 170 + 300}ms` : '0ms'}`,
                      }} />
                    {line.mark}
                  </span>
                  {line.after}
                </p>
              </div>
            )
          })}
        </div>

        {/* Reading it */}
        <div className="absolute inset-x-0 top-0 h-24 border-b-2 border-teal-500"
          style={{
            background: 'linear-gradient(to bottom, rgba(20,184,166,0), rgba(20,184,166,.16))',
            transform: `translateY(${act === 0 && beat >= 2 ? 310 : -100}px)`,
            opacity: act === 0 && beat >= 2 ? 1 : 0,
            transition: `transform 1500ms ${EASE_MOVE}, opacity 300ms ${EASE_OUT}`,
          }} />

        <div className="absolute inset-x-6 bottom-6 flex flex-wrap gap-1.5">
          {S.read_chips.map((chip, i) => {
            const on = act === 0 && beat >= 2
            return (
              <span key={chip} className="rounded-lg bg-teal-50 px-2.5 py-1 text-[12.5px] font-medium text-teal-800"
                style={{
                  opacity: on ? 1 : 0,
                  transform: on ? 'none' : 'translateY(6px) scale(.96)',
                  transition: `opacity 260ms ${EASE_OUT} ${on ? 1300 + i * 110 : 0}ms, transform 360ms ${EASE_OUT} ${on ? 1300 + i * 110 : 0}ms`,
                }}>
                {chip}
              </span>
            )
          })}
        </div>

        <p dir="auto" className="absolute inset-x-6 bottom-6 rounded-lg bg-teal-700 px-3 py-2 text-[12.5px] font-semibold text-white text-start truncate"
          style={{
            opacity: act === 2 && beat >= 2 ? 1 : 0,
            transform: act === 2 && beat >= 2 ? 'none' : 'translateY(10px) scale(.96)',
            transition: `opacity 240ms ${EASE_OUT}, transform 420ms ${EASE_OUT}`,
          }}>
          {S.stamp.replace('{job}', L.jobs[1].title)}
        </p>
      </div>

      {/* The jobs */}
      {jobs.map(({ job, score, rank }, i) => {
        const y = act === 2 ? (rank === 0 ? 0 : 150 + rank * 30) : 44 + (sorted ? rank : i) * ROW
        const visible = act === 1 || (act === 2 && rank === 0)
        return (
          <div key={job.title} dir="auto"
            className={`absolute start-[14px] w-[352px] h-[70px] flex items-center justify-between gap-3 rounded-[18px] bg-white px-4 shadow-floating ${sorted && rank === 0 ? 'ring-2 ring-teal-300' : ''}`}
            style={{
              transform: `translate(${visible || act === 2 ? 0 : 56 * flip}px, ${y}px)`,
              opacity: visible ? 1 : 0,
              pointerEvents: 'none',
              transition: `transform 720ms ${EASE_MOVE} ${act === 1 && beat === 0 ? i * 80 : 0}ms, opacity 300ms ${EASE_OUT} ${act === 1 && beat === 0 ? i * 80 : 0}ms`,
            }}>
            <div className="min-w-0 text-start">
              <p className="truncate text-[15px] font-bold tracking-tight text-slate-900">{job.title}</p>
              <p className="text-[12.5px] text-slate-500">{job.place}</p>
            </div>
            <LiveRing target={act === 2 || (act === 1 && beat >= 1) ? score : 0} />
          </div>
        )
      })}
    </div>
  )
}

export function WelcomeScene({ name, onStart, headerEnd }: {
  name: string | null
  onStart: () => void
  headerEnd: React.ReactNode
}) {
  const S = useI18n().t.onboarding.showcase
  const [reduced] = useState(prefersReduced)
  const [act, setAct] = useState(0)
  const [beat, setBeat] = useState(reduced ? 2 : 0)
  const [auto, setAuto] = useState(!reduced)
  const [run, setRun] = useState(0)

  useEffect(() => {
    if (reduced) { setBeat(2); return }
    setBeat(0)
    const timers = BEATS[act].map((ms, i) => setTimeout(() => setBeat(i + 1), ms))
    return () => timers.forEach(clearTimeout)
  }, [act, run, reduced])

  useEffect(() => {
    if (!auto) return
    const id = setTimeout(() => { if (act < 2) setAct(act + 1); else setAuto(false) }, ACT_MS[act])
    return () => clearTimeout(id)
  }, [act, auto, run])

  const first = name?.trim().split(/\s+/)[0]

  return (
    <KycShell
      headerEnd={headerEnd}
      aside={
        <div className="relative max-lg:h-[250px] lg:h-[560px] flex flex-col items-center justify-center overflow-visible">
          <Stage act={act} beat={beat} name={name} />
          <p className="absolute -bottom-1 lg:-bottom-6 inset-x-0 text-center text-[13px] text-slate-600">{S.example}</p>
        </div>
      }
    >
      <h1 dir="auto" className={`${kycTitle} text-start [overflow-wrap:anywhere]`}>
        {first ? S.greeting.replace('{name}', first) : S.title}
      </h1>
      <p className={kycSub}>{S.subtitle}</p>

      <ol className="mt-7 space-y-1.5">
        {S.steps.map((step, i) => {
          const on = act === i
          return (
            <li key={step.title} className={`relative overflow-hidden rounded-2xl transition-[background-color,box-shadow] duration-ja-ui ${on ? 'bg-white/70 shadow-elevation-1' : ''}`}>
              <button type="button" aria-current={on ? 'step' : undefined}
                onClick={() => { setAuto(false); setAct(i); setRun(r => r + 1) }}
                className="w-full flex gap-4 px-4 py-3.5 text-start rounded-2xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600">
                <span aria-hidden="true" className={`w-4 shrink-0 text-[16px] leading-snug font-semibold tabular-nums transition-colors duration-ja-ui ${on ? 'text-teal-700' : 'text-slate-500'}`}>{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className={`block text-[16px] leading-snug font-semibold tracking-tight transition-colors duration-ja-ui ${on ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900'}`}>{step.title}</span>
                  <span className={`grid transition-[grid-template-rows,opacity] duration-ja-enter ease-ja-out motion-reduce:transition-none ${on ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}>
                    <span className="overflow-hidden">
                      <span className="block pt-1 lg:min-h-[53px] text-[15px] leading-relaxed text-slate-600">{step.body}</span>
                    </span>
                  </span>
                </span>
              </button>
              {on && auto && (
                <span key={run} aria-hidden="true" className="absolute inset-x-0 bottom-0 h-0.5 bg-teal-600 origin-left rtl:origin-right animate-ja-fill"
                  style={{ animationDuration: `${ACT_MS[i]}ms` }} />
              )}
            </li>
          )
        })}
      </ol>

      <button type="button" onClick={onStart} className={`mt-5 ${kycPrimary} max-lg:ms-14 max-lg:w-[calc(100%-3.5rem)]`}>{S.cta}</button>
      {!reduced && (
        <button type="button"
          onClick={() => {
            if (auto) { setAuto(false); return }
            setAct(0); setAuto(true); setRun(r => r + 1)
          }}
          className="mt-2 mx-auto block min-h-[44px] px-3 text-[14px] font-medium text-slate-600 hover:text-slate-900 transition-colors duration-ja-ui">
          {auto ? S.pause : S.replay}
        </button>
      )}
    </KycShell>
  )
}
