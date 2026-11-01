'use client'

// ── Public landing page (signed-out visitors) ───────────────────────────────
//
// Rebuilt in the November 2026 redesign (docs/design-redesign.md, phase 2) on
// the English prototype Ron approved. The page shows the product instead of
// describing it: a match feed whose front score rises, a feed that sorts
// itself, a score that breaks into its parts, a CV line rewritten, Ariel in
// her real panel and colours, real limits, and questions answered the way
// Ariel answers them. Every number on it is real; the jobs, Maya's CV and the
// conversation are labelled examples.
//
// Motion follows the redesign rules: one ease-out curve, transform and
// opacity only, nothing hidden before hydration, and the OS reduced-motion
// setting turns every sequence into its end state.

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { Logo } from '@/components/ui/Logo'
import { getScoreBand } from '@/lib/scoreBand'
import { useChat } from '@/contexts/ChatContext'

const EASE = 'cubic-bezier(0.23, 1, 0.32, 1)'

// ── Hooks ────────────────────────────────────────────────────────────────────

function useReducedMotion() {
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

/** True once the element has scrolled into view; never goes back to false. */
function useInView<T extends HTMLElement>(threshold = 0.25) {
  const ref = useRef<T>(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setInView(true); io.disconnect() }
    }, { threshold })
    io.observe(el)
    return () => io.disconnect()
  }, [threshold])
  return [ref, inView] as const
}

/** Hidden only after hydration and until in view, so nothing is lost without
 *  script and the first paint is complete. */
function useReveal<T extends HTMLElement>() {
  const [ref, inView] = useInView<T>(0.2)
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  const style = mounted && !inView
    ? { opacity: 0, transform: 'translateY(14px)' }
    : { opacity: 1, transform: 'none', transition: `opacity 600ms ${EASE}, transform 700ms ${EASE}` }
  return [ref, style] as const
}

/** Like useReveal, for a list: item i follows the one before by `step` ms. */
function useStagger<T extends HTMLElement>(reduced: boolean, step = 90) {
  const [ref, inView] = useInView<T>(0.2)
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  const style = (i: number) => reduced ? {} : mounted && !inView
    ? { opacity: 0, transform: 'translateY(18px)' }
    : { opacity: 1, transform: 'none', transition: `opacity 600ms ${EASE} ${i * step}ms, transform 800ms ${EASE} ${i * step}ms` }
  return [ref, style] as const
}

function useCountUp(target: number, active: boolean, reduced: boolean, ms = 1000, from = 0) {
  const [value, setValue] = useState(from)
  useEffect(() => {
    if (!active) return
    if (reduced) { setValue(target); return }
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / ms)
      setValue(from + (target - from) * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, active, reduced, ms, from])
  return value
}

// ── Small pieces ─────────────────────────────────────────────────────────────

function Ring({ value, size = 72 }: { value: number; size?: number }) {
  const band = getScoreBand(value)
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90" aria-hidden="true">
        <circle cx="18" cy="18" r="15.9" fill="none" stroke={band.hexBg} strokeWidth="3.2" pathLength={100} />
        <circle cx="18" cy="18" r="15.9" fill="none" stroke={band.hexFg} strokeWidth="3.2" strokeLinecap="round"
          pathLength={100} strokeDasharray={`${value} 100`} />
      </svg>
      <span className="absolute inset-0 grid place-items-center font-bold tabular-nums tracking-tight"
        style={{ color: band.key === 'moderate' ? '#B45309' : band.hexFg, fontSize: size * 0.21 }}>
        {value.toFixed(1)}
      </span>
    </div>
  )
}

function Check({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className={`w-[18px] h-[18px] shrink-0 mt-px ${className}`}>
      <path d="M5 10.5l3.2 3L15 6.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Gap() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className="w-[18px] h-[18px] shrink-0 mt-px text-slate-400">
      <circle cx="10" cy="10" r="6.5" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

function ArielAvatar({ size = 32 }: { size?: number }) {
  return (
    <span aria-hidden="true" className="grid place-items-center rounded-full text-white font-semibold shrink-0"
      style={{ width: size, height: size, fontSize: size * 0.42, background: 'var(--ja-gradient-intelligence)', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.25)' }}>
      A
    </span>
  )
}

function TypingDots({ label }: { label: string }) {
  return (
    <span role="status" aria-label={label} className="inline-flex items-center gap-1 px-4 py-3 bg-white border border-slate-100 rounded-2xl rounded-ss-sm">
      {[0, 1, 2].map(i => (
        <span key={i} className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: `${i * 140}ms` }} />
      ))}
    </span>
  )
}

/** Ariel's message bubbles, in the product's own colours: the user on teal-50
 *  to the right, Ariel on white with a slate-100 border beside her avatar. */
function Bubble({ from, children }: { from: 'ai' | 'me'; children: ReactNode }) {
  if (from === 'me') {
    return (
      <div className="flex justify-end animate-ja-rise">
        <div dir="auto" className="max-w-[85%] rounded-2xl rounded-se-sm bg-teal-50 px-4 py-2.5 text-[14px] leading-relaxed text-slate-900 text-start">
          {children}
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-2.5 animate-ja-rise">
      <ArielAvatar size={28} />
      <div dir="auto" className="max-w-[85%] rounded-2xl rounded-ss-sm border border-slate-100 bg-white px-4 py-2.5 text-[14px] leading-relaxed text-slate-800 text-start">
        {children}
      </div>
    </div>
  )
}

const btnPrimary = 'inline-flex items-center justify-center gap-2 rounded-xl bg-ja-primaryHover text-white font-semibold tracking-tight transition-[background-color,transform] duration-ja-ui hover:bg-ja-harbor active:scale-[0.97] active:duration-ja-press'

// ── Header ───────────────────────────────────────────────────────────────────

function LandingHeader() {
  const L = useI18n().t.landing.nav
  return (
    <header className="sticky top-0 z-40 ja-glass border-b border-slate-100/70">
      <div className="max-w-6xl mx-auto px-4 sm:px-8 h-16 flex items-center gap-6">
        <Link href="/" aria-label={L.home} className="shrink-0 rounded-lg"><Logo size={28} /></Link>
        <nav className="hidden md:flex items-center gap-7 text-[14px] text-slate-600" aria-label={L.home}>
          <a href="#how" className="hover:text-slate-900 transition-colors">{L.links.how}</a>
          <a href="#ariel" className="hover:text-slate-900 transition-colors">{L.links.ariel}</a>
          <a href="#faq" className="hover:text-slate-900 transition-colors">{L.links.faq}</a>
        </nav>
        <div className="ms-auto flex items-center gap-2 sm:gap-3">
          <LanguageSwitcher className="shrink-0" />
          {/* Log in is the main action (Ron, 2026-10-31); a visitor without an
              account finds sign-up on the login page, or here. */}
          <Link href="/signup" className="hidden sm:inline-flex h-10 px-3 items-center rounded-lg text-[14px] font-medium text-slate-700 hover:text-slate-900 hover:bg-slate-100/70 transition-colors whitespace-nowrap">
            {L.sign_up}
          </Link>
          <Link href="/login" className={`${btnPrimary} inline-flex h-10 px-4 text-[14px] rounded-lg`}>
            {L.sign_in}
          </Link>
        </div>
      </div>
    </header>
  )
}

// ── Hero: the feed, with the front score rising ─────────────────────────────

function HeroFeed({ reduced }: { reduced: boolean }) {
  const { t, dir } = useI18n()
  const L = t.landing
  const flip = dir === 'rtl' ? -1 : 1
  const [mounted, setMounted] = useState(false)
  const [risen, setRisen] = useState(false)
  const [showGain, setShowGain] = useState(false)
  const score = useCountUp(82.4, risen, reduced, 900, 79)
  const tiltRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMounted(true)
    if (reduced) { setRisen(true); return }
    const a = setTimeout(() => { setRisen(true); setShowGain(true) }, 1500)
    const b = setTimeout(() => setShowGain(false), 4200)
    return () => { clearTimeout(a); clearTimeout(b) }
  }, [reduced])

  // Gentle tilt toward a fine pointer, eased each frame so it never snaps.
  useEffect(() => {
    const el = tiltRef.current
    if (!el || reduced || !window.matchMedia('(pointer: fine)').matches) return
    let raf = 0, tx = 0, ty = 0, x = 0, y = 0
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      tx = ((e.clientX - r.left) / r.width - 0.5) * 2
      ty = ((e.clientY - r.top) / r.height - 0.5) * 2
    }
    const onLeave = () => { tx = 0; ty = 0 }
    const loop = () => {
      x += (tx - x) * 0.08; y += (ty - y) * 0.08
      el.style.transform = `perspective(1200px) rotateY(${x * 4}deg) rotateX(${-y * 4}deg)`
      raf = requestAnimationFrame(loop)
    }
    const host = el.parentElement!
    host.addEventListener('pointermove', onMove)
    host.addEventListener('pointerleave', onLeave)
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); host.removeEventListener('pointermove', onMove); host.removeEventListener('pointerleave', onLeave) }
  }, [reduced])

  const fan = (i: number) => {
    const rest = [
      `translateX(${-36 * flip}px) rotate(${-3 * flip}deg) scale(.94)`,
      `translateX(${40 * flip}px) rotate(${2.5 * flip}deg) scale(.97)`,
      'none',
    ][i]
    return {
      transform: mounted ? rest : 'translateY(28px) scale(.96)',
      opacity: mounted ? 1 : 0,
      transition: `transform 900ms ${EASE} ${i * 90}ms, opacity 500ms ${EASE} ${i * 90}ms`,
    }
  }

  const back = [{ job: L.jobs[2], s: 58 }, { job: L.jobs[1], s: 91.2 }]
  return (
    <div className="relative" role="group" aria-label={L.hero.feed_label}>
      <div ref={tiltRef} className="relative sm:h-[460px] will-change-transform">
        {back.map(({ job, s }, i) => (
          <div key={job.title} aria-hidden="true" style={{ ...fan(i), top: i === 0 ? 0 : 68 }}
            className="absolute inset-x-0 mx-auto w-full max-w-[420px] rounded-[20px] bg-white shadow-elevation-2 px-6 py-5 hidden sm:block">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div dir="ltr" className="font-bold text-[17px] tracking-tight text-slate-900 text-start">{job.title}</div>
                <div className="text-[14px] text-slate-500">{job.place}</div>
              </div>
              <Ring value={s} size={64} />
            </div>
          </div>
        ))}

        <article style={{ ...fan(2) }}
          className="relative sm:absolute sm:top-[150px] inset-x-0 mx-auto w-full max-w-[420px] rounded-[20px] bg-white shadow-floating px-5 sm:px-6 py-5 grid gap-3 z-10">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div dir="ltr" className="font-bold text-[18px] tracking-tight text-slate-900 text-start">{L.jobs[0].title}</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {[L.jobs[0].place, L.hybrid].map(tag => (
                  <span key={tag} className="text-[12.5px] text-slate-600 bg-slate-100 rounded-full px-2.5 py-0.5">{tag}</span>
                ))}
                <span className="text-[12.5px] text-slate-600 bg-white ring-1 ring-slate-200 rounded-full px-2.5 py-0.5">LinkedIn</span>
              </div>
            </div>
            <div className="relative">
              <Ring value={score} size={76} />
              <span aria-hidden="true"
                className="absolute -top-3 end-0 whitespace-nowrap rounded-full bg-emerald-50 text-emerald-700 text-[12px] font-semibold px-2 py-0.5 shadow-elevation-1"
                style={{ opacity: showGain ? 1 : 0, transform: showGain ? 'translateY(-6px)' : 'translateY(4px)', transition: `opacity 300ms ${EASE}, transform 500ms ${EASE}` }}>
                {L.hero.score_up.replace('{n}', '3.4')}
              </span>
            </div>
          </div>
          <div className="text-[14px] font-semibold text-teal-700">{L.hero.band}</div>
          <ul className="grid gap-2 border-t border-slate-100 pt-3">
            {L.hero.reasons.map(r => (
              <li key={r} className="flex gap-2 text-[14px] leading-snug text-slate-700"><Check className="text-emerald-600" />{r}</li>
            ))}
            <li className="flex gap-2 text-[14px] leading-snug text-slate-700"><Gap />{L.hero.gap}</li>
          </ul>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <a href="#how" className="h-10 px-4 inline-flex items-center rounded-lg bg-teal-50 text-teal-800 text-[14px] font-semibold transition-[background-color,transform] hover:bg-teal-100 active:scale-[0.97]">{L.hero.tailor}</a>
            <a href="#ariel" className="h-10 px-3 inline-flex items-center rounded-lg text-[14px] font-semibold text-violet-700 hover:bg-violet-50 transition-colors">{L.hero.ask}</a>
          </div>
        </article>
      </div>
      <p className="text-center text-[12.5px] text-slate-500 mt-4 sm:mt-0">{L.hero.example}</p>
    </div>
  )
}

function Hero({ reduced }: { reduced: boolean }) {
  const L = useI18n().t.landing.hero
  // The headline rises a word at a time, then the line under it, then the
  // actions. CSS only, so it plays without script; reduced motion skips it.
  const lines = L.h1.map(line => line.split(' '))
  const rise = (ms: number) => ({ style: reduced ? undefined : { animationDelay: `${ms}ms` } })
  const count = lines.flat().length
  const after = count * 70 + 120
  return (
    <section className="relative isolate overflow-clip" aria-labelledby="landing-h1">
      <div aria-hidden="true" className="absolute inset-0 -z-10"
        style={{ background: 'radial-gradient(50% 60% at 75% 40%, #F0FDFA, rgba(240,253,250,0) 70%), radial-gradient(35% 45% at 95% 90%, rgba(245,243,255,.9), rgba(245,243,255,0) 70%)' }} />
      <div className="max-w-6xl mx-auto px-4 sm:px-8 pt-10 sm:pt-16 pb-20 sm:pb-28 grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
        <div className="grid gap-5">
          <h1 id="landing-h1" className="text-[38px] sm:text-[52px] lg:text-[58px] leading-[1.05] font-extrabold tracking-[-0.04em] text-slate-900 [text-wrap:balance]">
            {lines.map((words, li) => {
              const first = lines.slice(0, li).flat().length
              return (
                <span key={li} className={`block ${li === 0 ? 'text-slate-500' : 'text-slate-900'}`}>
                  {words.map((w, i) => (
                    <span key={i}>
                      <span {...rise((first + i) * 70 + li * 160)} className={`inline-block ${reduced ? '' : 'animate-ja-rise'}`}>{w}</span>
                      {i < words.length - 1 && ' '}
                    </span>
                  ))}
                </span>
              )
            })}
          </h1>
          <p {...rise(after)} className={`text-[18px] sm:text-[20px] leading-relaxed text-slate-600 max-w-[34rem] ${reduced ? '' : 'animate-ja-rise'}`}>{L.sub}</p>
          <div {...rise(after + 100)} className={`flex flex-wrap items-center gap-3 mt-1 ${reduced ? '' : 'animate-ja-rise'}`}>
            <Link href="/login" className={`${btnPrimary} h-[52px] px-7 text-[16px]`}>{L.cta}</Link>
            <a href="#how" className="h-[52px] px-2 inline-flex items-center text-[16px] font-semibold text-teal-800 underline decoration-transparent underline-offset-[5px] hover:decoration-current transition-[text-decoration-color]">
              {L.link}
            </a>
          </div>
          <p {...rise(after + 200)} className={`flex items-center gap-2 text-[14px] text-slate-500 ${reduced ? '' : 'animate-ja-rise'}`}><Check className="text-teal-600" />{L.fact}</p>
        </div>
        <HeroFeed reduced={reduced} />
      </div>
    </section>
  )
}

// ── Why JobApply: three reasons, right under the hero ──────────────────────

function Why({ reduced }: { reduced: boolean }) {
  const L = useI18n().t.landing.hero
  const [ref, style] = useStagger<HTMLUListElement>(reduced, 120)
  const [lineRef, lineOn] = useInView<HTMLDivElement>(0.4)
  return (
    <section aria-label={L.why_label} className="-mt-6 sm:-mt-10 pb-16 sm:pb-24">
      <div ref={lineRef} className="max-w-6xl mx-auto px-4 sm:px-8">
        <ul ref={ref} className="grid sm:grid-cols-3 gap-x-10 gap-y-8">
          {L.why.map((w, i) => (
            <li key={w.title} style={style(i)} className="relative grid gap-2 pt-6">
              <span aria-hidden="true" className="absolute top-0 inset-x-0 h-px bg-slate-200" />
              <span aria-hidden="true" className="absolute top-0 start-0 w-16 h-[3px] -mt-px rounded-full bg-teal-600 origin-left rtl:origin-right"
                style={{ transform: `scaleX(${lineOn || reduced ? 1 : 0})`, transition: reduced ? undefined : `transform 900ms ${EASE} ${200 + i * 120}ms` }} />
              <h2 className="text-[20px] font-bold tracking-[-0.015em] text-slate-900">{w.title}</h2>
              <p className="text-[16px] leading-relaxed text-slate-600">{w.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

// ── Pain: the search today, lit word by word as it scrolls past ────────────
//
// Apple's pinned statement: the paragraph holds still while each word lights
// up with scroll progress, so the reader moves through the evenings one
// sentence at a time. The last line, the turn, lights in teal.

function PainLines({ reduced }: { reduced: boolean }) {
  const P = useI18n().t.landing.pain
  const outer = useRef<HTMLElement>(null)
  // 1 = every word lit: the state before script runs, and under reduced motion.
  const [progress, setProgress] = useState(1)

  useEffect(() => {
    const el = outer.current
    if (!el || reduced) { setProgress(1); return }
    let raf = 0
    const read = () => {
      raf = 0
      const r = el.getBoundingClientRect()
      const span = Math.max(1, r.height - window.innerHeight)
      setProgress(Math.min(1, Math.max(0, -r.top / span)))
    }
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(read) }
    read()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [reduced])

  const last = P.lines.length - 1
  const total = P.lines.join(' ').split(' ').length
  // Finishes a little before the pin releases, so the full text is read still.
  const lit = progress * 1.1 * total
  let n = 0

  return (
    <section ref={outer} aria-label={P.label} className={reduced ? 'py-24 sm:py-32' : 'h-[240vh]'}>
      <div className={reduced ? '' : 'sticky top-0 h-[100svh] flex items-center'}>
        <p className="max-w-5xl mx-auto px-4 sm:px-8 text-[30px] sm:text-[44px] lg:text-[52px] leading-[1.15] font-bold tracking-[-0.035em]">
          {P.lines.map((line, li) => (
            <span key={li} className={li === last ? 'block mt-6 sm:mt-10' : undefined}>
              {line.split(' ').map((w, wi) => {
                const on = n++ < lit
                return (
                  <span key={wi} className="transition-colors duration-300"
                    style={{ color: on ? (li === last ? '#0F766E' : '#0F172A') : '#CBD5E1' }}>
                    {w}{' '}
                  </span>
                )
              })}
            </span>
          ))}
        </p>
      </div>
    </section>
  )
}

function Tile({ t, big, active, reduced, style }: {
  t: { n?: number; prefix?: string; suffix?: string; value?: string; label: string }
  big: boolean; active: boolean; reduced: boolean; style: React.CSSProperties
}) {
  const v = useCountUp(t.n ?? 0, active, reduced, 1400)
  const shown = t.n === undefined ? t.value : `${t.prefix ?? ''}${Math.round(v).toLocaleString('en-US')}${t.suffix ?? ''}`
  return (
    <div style={style}
      className={`rounded-[24px] sm:rounded-[28px] p-5 sm:p-8 grid content-between gap-4 sm:gap-6 ${big
        ? 'col-span-2 lg:col-span-1 lg:row-span-2 min-h-[220px] lg:min-h-0 text-white'
        : 'bg-white shadow-elevation-1 ring-1 ring-slate-100 min-h-[170px] sm:min-h-[200px]'}`}>
      {/* dir=ltr keeps "100+" and "~10,000" in order inside Hebrew text. */}
      <span dir={t.n === undefined ? undefined : 'ltr'} className={`text-start font-extrabold tracking-[-0.05em] tabular-nums leading-none ${big ? 'text-[60px] sm:text-[80px] lg:text-[64px] xl:text-[72px]' : t.n === undefined ? 'text-[26px] sm:text-[44px] text-teal-700' : 'text-[44px] sm:text-[64px] text-slate-900'}`}>
        {shown}
      </span>
      <span className={`text-[15px] sm:text-[17px] leading-snug max-w-[22rem] ${big ? 'text-teal-50' : 'text-slate-600'}`}>{t.label}</span>
    </div>
  )
}

function Answer({ reduced }: { reduced: boolean }) {
  const P = useI18n().t.landing.pain
  const [headRef, headStyle] = useReveal<HTMLDivElement>()
  const [gridRef, style] = useStagger<HTMLDivElement>(reduced, 90)
  const [countRef, counting] = useInView<HTMLDivElement>(0.3)
  return (
    <section className="pb-20 sm:pb-32" aria-labelledby="answer-h2">
      <div className="max-w-6xl mx-auto px-4 sm:px-8">
        <div ref={headRef} style={headStyle} className="max-w-3xl mx-auto text-center grid gap-5 justify-items-center mb-12 sm:mb-16">
          <h2 id="answer-h2" className="text-[44px] sm:text-[64px] lg:text-[80px] leading-none font-extrabold tracking-[-0.045em] text-slate-900">{P.answer_h2}</h2>
          <p className="text-[18px] sm:text-[21px] leading-relaxed text-slate-600 max-w-2xl">{P.answer_lead}</p>
          <Link href="/login" className={`${btnPrimary} mt-2 h-[52px] px-7 text-[16px]`}>{P.cta}</Link>
        </div>
        <div ref={countRef}>
          <div ref={gridRef} className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 lg:grid-rows-2">
            {P.tiles.map((t, i) => (
              <Tile key={t.label} t={t} big={i === 0} active={counting} reduced={reduced}
                style={{ ...style(i), ...(i === 0 ? { background: 'linear-gradient(160deg, #0F766E, #134E4A)' } : {}) }} />
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

// ── Story: feed → score → CV, with a sticky stage on desktop ────────────────

const FEED = [
  { job: 1, score: 91.2 }, { job: 0, score: 82.4 }, { job: 3, score: 74.0 }, { job: 2, score: 58.0 },
]
const SCRAMBLED = [2, 0, 3, 1] // display slot of FEED[i] before sorting

function FeedScene({ active }: { active: boolean }) {
  const L = useI18n().t.landing
  const ROW = 76
  return (
    <div className="relative rounded-[24px] bg-white shadow-floating p-3" style={{ height: ROW * 4 + 24 }}>
      {FEED.map((f, i) => {
        const slot = active ? i : SCRAMBLED[i]
        return (
          <div key={f.job} className="absolute inset-x-3 flex items-center justify-between gap-3 rounded-2xl px-4 h-[68px] bg-white"
            style={{ top: 12, transform: `translateY(${slot * ROW}px)`, transition: `transform 800ms ${EASE} ${i * 60}ms`, boxShadow: slot === 0 && active ? 'inset 0 0 0 1px #CCFBF1' : 'inset 0 0 0 1px #F1F5F9' }}>
            <div className="min-w-0">
              <div dir="ltr" className="font-semibold text-[15px] text-slate-900 truncate text-start">{L.jobs[f.job].title}</div>
              <div className="text-[13px] text-slate-500">{L.jobs[f.job].place}</div>
            </div>
            <Ring value={f.score} size={48} />
          </div>
        )
      })}
    </div>
  )
}

function ScorePart({ part, i, active, reduced }: { part: { label: string; points: number; max: number }; i: number; active: boolean; reduced: boolean }) {
  const v = useCountUp(part.points, active, reduced, 1100)
  return (
    <div className="grid gap-2">
      <div className="flex justify-between gap-4 text-[14px]">
        <span className="font-semibold text-slate-900">{part.label}</span>
        <span dir="ltr" className="tabular-nums text-slate-500"><span className="font-semibold text-slate-900">{v.toFixed(1)}</span> / {part.max}</span>
      </div>
      <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
        <div className="h-full rounded-full origin-left rtl:origin-right"
          style={{ background: i === 0 ? 'var(--ja-gradient-intelligence)' : '#0D9488', transform: `scaleX(${active ? part.points / part.max : 0})`, transition: `transform 1000ms ${EASE} ${150 + i * 120}ms` }} />
      </div>
    </div>
  )
}

function ScoreScene({ active, reduced }: { active: boolean; reduced: boolean }) {
  const S = useI18n().t.landing.story
  const v = useCountUp(82.4, active, reduced, 1100)
  return (
    <div className="rounded-[24px] bg-white shadow-floating p-6 sm:p-8 grid gap-6">
      <div className="flex items-baseline gap-2">
        <span className="text-[64px] sm:text-[80px] leading-none font-extrabold tracking-[-0.05em] tabular-nums text-teal-600">{v.toFixed(1)}</span>
        <span className="text-[20px] font-semibold text-slate-400">/ 100</span>
      </div>
      {S.parts.map((p, i) => <ScorePart key={p.label} part={p} i={i} active={active} reduced={reduced} />)}
      <p className="text-[14px] text-slate-500 border-t border-slate-100 pt-4">{S.note}</p>
    </div>
  )
}

const CV_BEFORE = ['Responsible for customer accounts and renewals.', 'Worked with R&D on customer issues.']
const CV_AFTER = ['Owned renewals for B2B customer accounts.', 'Partnered with R&D to resolve customer-reported issues.']

function CvScene({ active, reduced }: { active: boolean; reduced: boolean }) {
  const S = useI18n().t.landing.story
  const [tailored, setTailored] = useState(false)
  const touched = useRef(false)
  useEffect(() => {
    if (!active || touched.current) return
    const id = setTimeout(() => setTailored(true), reduced ? 0 : 900)
    return () => clearTimeout(id)
  }, [active, reduced])
  const choose = (v: boolean) => { touched.current = true; setTailored(v) }
  const lines = tailored ? CV_AFTER : CV_BEFORE
  return (
    <div className="grid gap-4">
      <div role="group" aria-label="CV" className="relative inline-grid grid-cols-2 self-start justify-self-start rounded-xl bg-slate-100 p-1 shadow-[inset_0_1px_2px_rgba(15,23,42,.06)]">
        <span aria-hidden="true" className="absolute top-1 bottom-1 start-1 w-[calc(50%-4px)] rounded-lg bg-white shadow-elevation-1"
          style={{ transform: tailored ? 'translateX(calc(100% * var(--seg-dir, 1)))' : 'none', transition: `transform 340ms ${EASE}` }} />
        {[false, true].map(v => (
          <button key={String(v)} type="button" aria-pressed={tailored === v} onClick={() => choose(v)}
            className={`relative z-10 px-5 h-10 rounded-lg text-[14px] font-semibold transition-colors ${tailored === v ? 'text-slate-900' : 'text-slate-500'}`}>
            {v ? S.tailored : S.original}
          </button>
        ))}
      </div>
      <div dir="ltr" className="rounded-[24px] bg-white shadow-floating p-6 sm:p-8 grid gap-3 text-left" aria-live="polite">
        <div>
          <div className="font-bold text-[18px] tracking-tight text-slate-900">Maya Cohen</div>
          <div className="text-[14px] text-slate-500">Customer Success Manager, 2021 to today</div>
        </div>
        {lines.map(line => (
          <p key={line} className={`rounded-lg px-4 py-3 text-[14px] leading-relaxed animate-ja-rise ${tailored ? 'bg-teal-50 text-slate-900 shadow-[inset_3px_0_0_#0D9488]' : 'bg-slate-50 text-slate-600'}`}>
            {line}
          </p>
        ))}
        <p dir="auto" className={`flex gap-2 text-[13px] text-teal-800 transition-opacity duration-ja-ui ${tailored ? 'opacity-100' : 'opacity-0'}`}>
          <Check className="text-teal-600 w-4 h-4" />{S.source}
        </p>
      </div>
    </div>
  )
}

/** Below md the scene sits under its text, so it plays when it is itself on
 *  screen, not when its step reaches the middle (it showed 0.0 until then). */
function InlineScene({ render }: { render: (on: boolean) => ReactNode }) {
  const [ref, on] = useInView<HTMLDivElement>(0.45)
  return <div ref={ref} className="md:hidden mt-4">{render(on)}</div>
}

function Story({ reduced }: { reduced: boolean }) {
  const { t, dir } = useI18n()
  const S = t.landing.story
  const [active, setActive] = useState(0)
  const [seen, setSeen] = useState([false, false, false])
  const stepRefs = useRef<(HTMLDivElement | null)[]>([])
  const [headRef, headStyle] = useReveal<HTMLDivElement>()

  useEffect(() => {
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (!e.isIntersecting) return
        const i = Number((e.target as HTMLElement).dataset.step)
        setActive(i)
        setSeen(s => s.map((v, j) => v || j === i))
      })
    }, { rootMargin: '-40% 0px -40% 0px' })
    stepRefs.current.forEach(el => el && io.observe(el))
    return () => io.disconnect()
  }, [])

  const scene = (i: number, on: boolean) =>
    i === 0 ? <FeedScene active={on} /> : i === 1 ? <ScoreScene active={on} reduced={reduced} /> : <CvScene active={on} reduced={reduced} />

  return (
    <section id="how" className="scroll-mt-20 py-20 sm:py-32" aria-labelledby="how-h2" style={{ ['--seg-dir' as string]: dir === 'rtl' ? -1 : 1 }}>
      <div className="max-w-6xl mx-auto px-4 sm:px-8">
        <div ref={headRef} style={headStyle} className="max-w-2xl mb-12 md:mb-4">
          <h2 id="how-h2" className="text-[36px] sm:text-[52px] leading-[1.05] font-bold tracking-[-0.035em] text-slate-900 [text-wrap:balance]">{S.h2}</h2>
          <p className="mt-5 text-[18px] sm:text-[20px] leading-relaxed text-slate-600">{S.lead}</p>
        </div>
        <div className="grid md:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] gap-12 md:gap-16">
          <div>
            {S.steps.map((s, i) => (
              <div key={s.title} data-step={i} ref={el => { stepRefs.current[i] = el }}
                className="md:min-h-[70vh] flex flex-col justify-center gap-3 py-8 md:py-0 transition-opacity duration-ja-enter"
                style={{ opacity: active === i ? 1 : undefined }}>
                <div className={`grid gap-3 transition-opacity duration-ja-enter ${active === i ? 'md:opacity-100' : 'md:opacity-35'}`}>
                  <h3 className="text-[24px] sm:text-[28px] font-bold tracking-[-0.02em] text-slate-900">{s.title}</h3>
                  <p className="text-[17px] leading-relaxed text-slate-600 max-w-md">{s.body}</p>
                  {i === S.steps.length - 1 && (
                    <div className="grid gap-2 justify-items-start mt-3">
                      <Link href="/login" className={`${btnPrimary} h-12 px-6 text-[15px]`}>{S.cta}</Link>
                      <span className="text-[14px] text-slate-500">{S.cta_note}</span>
                    </div>
                  )}
                </div>
                <InlineScene render={on => scene(i, on || seen[i])} />
              </div>
            ))}
          </div>
          <div className="hidden md:block">
            <div className="sticky top-[calc(50vh-240px)] h-[480px]">
              {[0, 1, 2].map(i => (
                <div key={i} aria-hidden={active !== i} className="absolute inset-0 flex items-center"
                  style={{ opacity: active === i ? 1 : 0, transform: active === i ? 'none' : 'translateY(16px) scale(.98)', transition: `opacity 400ms ${EASE}, transform 600ms ${EASE}`, pointerEvents: active === i ? 'auto' : 'none' }}>
                  <div className="w-full">{scene(i, seen[i])}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

// ── Ariel, in her real panel ─────────────────────────────────────────────────

type Msg = { from: 'ai' | 'me'; text: string; key: string }

function useConversation(reduced: boolean) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [typing, setTyping] = useState(false)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const clear = () => { timers.current.forEach(clearTimeout); timers.current = [] }
  useEffect(() => clear, [])

  /** Plays messages in order; each of Ariel's is preceded by a typing pause. */
  const play = useCallback((items: { from: 'ai' | 'me'; text: string }[], replace = false) => {
    clear()
    if (replace) setMsgs([])
    if (reduced) { setTyping(false); setMsgs(m => [...(replace ? [] : m), ...items.map((x, i) => ({ ...x, key: `${Date.now()}-${i}` }))]); return }
    let at = 0
    items.forEach((x, i) => {
      if (x.from === 'ai') {
        timers.current.push(setTimeout(() => setTyping(true), at))
        at += 900
      }
      timers.current.push(setTimeout(() => { setTyping(false); setMsgs(m => [...m, { ...x, key: `${Date.now()}-${i}` }]) }, at))
      at += 450
    })
  }, [reduced])
  return { msgs, typing, play }
}

function ArielPanel({ msgs, typing, scrollKey }: { msgs: Msg[]; typing: boolean; scrollKey: number }) {
  const A = useI18n().t.landing.ariel
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' }) }, [msgs.length, typing, scrollKey])
  return (
    <div className="rounded-[28px] bg-white shadow-[0_40px_80px_-40px_rgba(124,58,237,.45),0_1px_2px_rgba(15,23,42,.08)] overflow-hidden">
      <div className="flex items-center gap-3 px-5 h-16 border-b border-slate-100">
        <ArielAvatar size={36} />
        <span className="font-semibold text-[17px] text-slate-800">{A.name}</span>
        <span className="ms-auto text-[13px] text-slate-500">{A.example}</span>
      </div>
      <div ref={box} className="h-[340px] overflow-y-auto px-5 py-5 grid gap-4 content-start" aria-live="polite">
        {msgs.map(m => <Bubble key={m.key} from={m.from}>{m.text}</Bubble>)}
        {typing && <div className="flex items-start gap-2.5"><ArielAvatar size={28} /><TypingDots label={A.typing} /></div>}
      </div>
      <div className="flex items-center gap-3 px-5 py-4 border-t border-slate-100" aria-hidden="true">
        <div className="flex-1 h-11 rounded-2xl border border-violet-200 px-4 flex items-center text-[14px] text-slate-400">{A.placeholder}</div>
        <span className="w-11 h-11 rounded-full bg-slate-100 grid place-items-center text-slate-400">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" /></svg>
        </span>
      </div>
    </div>
  )
}

function ArielSection({ reduced }: { reduced: boolean }) {
  const A = useI18n().t.landing.ariel
  const [ref, inView] = useInView<HTMLDivElement>(0.35)
  const { msgs, typing, play } = useConversation(reduced)
  const [asked, setAsked] = useState<number | null>(null)
  const started = useRef(false)

  useEffect(() => {
    if (inView && !started.current) { started.current = true; play(A.intro as { from: 'ai' | 'me'; text: string }[], true) }
  }, [inView, play, A.intro])

  // Each option replaces the intro with its own example conversation.
  const ask = (i: number) => {
    started.current = true
    setAsked(i)
    play(A.chips[i].convo as { from: 'ai' | 'me'; text: string }[], true)
  }

  return (
    <section id="ariel" className="scroll-mt-16 relative isolate overflow-clip text-slate-50" style={{ background: 'var(--ja-gradient-abyss)' }} aria-labelledby="ariel-h2">
      <div aria-hidden="true" className="absolute -z-10 w-[720px] h-[720px] rounded-full -top-60 end-[-200px]" style={{ background: 'radial-gradient(closest-side, rgba(124,58,237,.38), transparent)' }} />
      <div aria-hidden="true" className="absolute -z-10 w-[520px] h-[520px] rounded-full -bottom-60 start-[-160px]" style={{ background: 'radial-gradient(closest-side, rgba(13,148,136,.30), transparent)' }} />
      <div ref={ref} className="max-w-6xl mx-auto px-4 sm:px-8 py-20 sm:py-32 grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
        <div className="grid gap-5">
          <h2 id="ariel-h2" className="text-[36px] sm:text-[52px] leading-[1.05] font-bold tracking-[-0.035em] [text-wrap:balance]">{A.h2}</h2>
          <p className="text-[18px] leading-relaxed text-slate-300 max-w-md">{A.lead}</p>
          <div role="group" aria-label={A.chips_label} className="flex flex-wrap gap-2 mt-2">
            {A.chips.map((c, i) => (
              <button key={c.q} type="button" aria-pressed={asked === i} onClick={() => ask(i)}
                className={`h-11 px-4 rounded-full text-[14px] font-medium ring-1 transition-[background-color,transform,box-shadow] duration-ja-ui active:scale-[0.97] focus-visible:outline-teal-200 ${asked === i ? 'bg-white text-slate-900 ring-white' : 'bg-white/10 text-slate-100 ring-white/15 hover:bg-white/15'}`}>
                {c.q}
              </button>
            ))}
          </div>
          <Link href="/login" className={`${btnPrimary} justify-self-start mt-3 h-12 px-6 text-[15px]`}>{A.cta}</Link>
        </div>
        <ArielPanel msgs={msgs} typing={typing} scrollKey={asked ?? -1} />
      </div>
    </section>
  )
}

// ── Questions: an editorial list, each answer in full ──────────────────────
//
// Deliberately unlike Ariel's chat above (Ron, 2026-10-31): numbered
// questions on rules, one open at a time, answers of a few paragraphs.

function Faq({ reduced }: { reduced: boolean }) {
  const Q = useI18n().t.landing.faq
  const [open, setOpen] = useState<number | null>(0)
  const [ref, style] = useStagger<HTMLUListElement>(reduced, 60)
  return (
    <section id="faq" className="scroll-mt-16 py-20 sm:py-28 bg-white border-t border-slate-100" aria-labelledby="faq-h2">
      <div className="max-w-6xl mx-auto px-4 sm:px-8 grid lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] gap-10 lg:gap-20 items-start">
        <div className="lg:sticky lg:top-24 grid gap-4 justify-items-start">
          <h2 id="faq-h2" className="text-[36px] sm:text-[52px] leading-[1.05] font-bold tracking-[-0.035em] text-slate-900 [text-wrap:balance]">{Q.h2}</h2>
          <p className="text-[17px] leading-relaxed text-slate-600">{Q.lead}</p>
          <p className="text-[15px] text-slate-500 mt-4">{Q.more}</p>
          <Link href="/login" className={`${btnPrimary} h-12 px-6 text-[15px]`}>{Q.cta}</Link>
        </div>
        <ul ref={ref} className="border-t border-slate-200">
          {Q.items.map((it, i) => {
            const isOpen = open === i
            return (
              <li key={it.q} style={style(i)} className="border-b border-slate-200">
                <h3>
                  <button type="button" id={`faq-q-${i}`} aria-expanded={isOpen} aria-controls={`faq-a-${i}`}
                    onClick={() => setOpen(isOpen ? null : i)}
                    className="group w-full min-h-[72px] py-5 flex items-center gap-4 sm:gap-6 text-start rounded-lg">
                    <span className={`w-7 shrink-0 text-[14px] font-semibold tabular-nums transition-colors duration-ja-ui ${isOpen ? 'text-teal-700' : 'text-slate-400'}`}>
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <span className="flex-1 text-[18px] sm:text-[20px] font-semibold tracking-[-0.01em] text-slate-900 group-hover:text-teal-800 transition-colors">{it.q}</span>
                    <span aria-hidden="true"
                      className={`w-9 h-9 shrink-0 rounded-full grid place-items-center ring-1 transition-[transform,background-color,color] duration-ja-ui ${isOpen ? 'rotate-45 bg-ja-primaryHover ring-transparent text-white' : 'ring-slate-200 text-slate-500 group-hover:ring-slate-300'}`}>
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
                    </span>
                  </button>
                </h3>
                <div id={`faq-a-${i}`} role="region" aria-labelledby={`faq-q-${i}`} hidden={!isOpen}
                  className="ps-11 sm:ps-[52px] pe-4 sm:pe-14 pb-7 -mt-1">
                  <div className={`grid gap-3 ${reduced ? '' : 'animate-ja-rise'}`}>
                    {it.a.map(p => <p key={p} className="text-[16px] leading-relaxed text-slate-600 max-w-[60ch]">{p}</p>)}
                    {it.link && (
                      <Link href={it.link.href} className="justify-self-start text-[15px] font-semibold text-teal-800 underline decoration-teal-800/30 underline-offset-4 hover:decoration-current transition-[text-decoration-color]">
                        {it.link.label}
                      </Link>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}

// ── Close ────────────────────────────────────────────────────────────────────

function Close() {
  const C = useI18n().t.landing.close
  const [ref, style] = useReveal<HTMLDivElement>()
  return (
    <section className="py-20 sm:py-28" aria-labelledby="close-h2">
      <div className="max-w-6xl mx-auto px-4 sm:px-8">
        <div ref={ref} style={style} className="relative isolate overflow-clip rounded-[32px] bg-white shadow-floating px-6 sm:px-16 py-16 sm:py-24 grid gap-5 justify-items-start text-slate-900">
          <div aria-hidden="true" className="absolute -z-10 w-[560px] h-[560px] rounded-full top-0 start-1/2" style={{ background: 'radial-gradient(closest-side, #F0FDFA, rgba(240,253,250,0))' }} />
          <h2 id="close-h2" className="text-[36px] sm:text-[56px] leading-[1.04] font-bold tracking-[-0.035em] max-w-[14ch] [text-wrap:balance]">{C.h2}</h2>
          <p className="text-[18px] text-slate-600">{C.body}</p>
          <Link href="/login" className={`${btnPrimary} mt-2 h-[52px] px-7 text-[16px]`}>
            {C.cta}
          </Link>
        </div>
      </div>
    </section>
  )
}

// ── Eliya, for questions before signing up ──────────────────────────────────
//
// Opposite the accessibility button (Ron, 2026-10-31), so the two never
// overlap. It opens the same support panel the footer's Help link opens.

function EliyaLauncher() {
  const E = useI18n().t.landing.eliya
  const { isEliyaOpen, openEliya } = useChat()
  if (isEliyaOpen) return null
  return (
    <button type="button" onClick={() => openEliya()} aria-label={E.label} title={E.title}
      className="fixed bottom-6 end-4 sm:end-6 z-30 h-12 w-12 sm:w-auto sm:ps-1.5 sm:pe-4 inline-flex items-center justify-center gap-2.5 rounded-full bg-white text-[14px] font-semibold text-slate-800 shadow-floating ring-1 ring-indigo-100 transition-transform duration-ja-ui hover:-translate-y-0.5 active:scale-[0.97] print:hidden">
      <span aria-hidden="true" className="w-9 h-9 rounded-full grid place-items-center text-white text-[14px] font-bold" style={{ background: '#4F46E5' }}>E</span>
      <span className="hidden sm:inline">{E.label}</span>
    </button>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function LandingPage() {
  const { t, locale } = useI18n()
  const L = t.landing
  const reduced = useReducedMotion()
  return (
    <div className="min-h-screen bg-ja-bg overflow-x-clip">
      <a href="#landing-main" className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:start-3 focus:z-50 focus:rounded-lg focus:bg-slate-900 focus:text-white focus:px-4 focus:py-2">
        {L.nav.skip}
      </a>
      <LandingHeader />
      <main id="landing-main">
        <Hero reduced={reduced} />
        <Why reduced={reduced} />
        <PainLines reduced={reduced} />
        <Answer reduced={reduced} />
        <Story reduced={reduced} />
        <ArielSection key={`ariel-${locale}`} reduced={reduced} />
        <Faq key={`faq-${locale}`} reduced={reduced} />
        <Close />
      </main>
      <EliyaLauncher />
    </div>
  )
}
