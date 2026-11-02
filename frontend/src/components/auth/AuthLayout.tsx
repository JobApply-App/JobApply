'use client'

import Link from 'next/link'
import { useI18n } from '@/contexts/I18nContext'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { Ring } from '@/components/landing/Ring'
import { Logo } from '@/components/ui/Logo'

// ── AuthLayout ───────────────────────────────────────────────────────────────
//
// Login and signup, in the landing's language: the teal panel of its closing
// section, the same example jobs sorted best first, and the form on plain white
// beside it. Below `lg` the panel goes and the form comes first, because on a
// phone someone here came to sign in.

function PanelFeed() {
  const { t, dir } = useI18n()
  const L = t.landing
  const flip = dir === 'rtl' ? -1 : 1
  const cards = [
    { job: L.jobs[1], score: 91.2, fan: `translateX(${-18 * flip}px) rotate(${-2 * flip}deg)` },
    { job: L.jobs[0], score: 82.4, fan: `translateX(${16 * flip}px) rotate(${1.5 * flip}deg)` },
    { job: L.jobs[3], score: 74.0, fan: 'none' },
  ]
  return (
    // Hidden on short screens, where the headline needs the room.
    <div role="group" aria-label={L.hero.feed_label} className="[@media(max-height:719px)]:hidden">
      <div className="max-w-[420px]">
        {cards.map(({ job, score, fan }, i) => (
          <div key={score} style={{ transform: fan, zIndex: i }} className={`relative ${i > 0 ? '-mt-1' : ''}`}>
            <div style={{ animationDelay: `${i * 90}ms` }}
              className="animate-ja-rise motion-reduce:animate-none flex items-center justify-between gap-4 rounded-[20px] bg-white shadow-floating px-5 py-4">
              <div className="min-w-0">
                <div dir="auto" className="font-bold text-[16px] tracking-tight text-slate-900 text-start truncate">{job.title}</div>
                <div className="text-[13px] text-slate-500">{job.place}</div>
              </div>
              <Ring value={score} size={52} />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-6 text-[13px] text-teal-100/80">{L.hero.example}</p>
    </div>
  )
}

interface AuthLayoutProps {
  children: React.ReactNode
  headline: string
  subline:  string
  /** The way back: `label` is shown, `aria` says where it goes. */
  back: { href: string; label: string; aria: string }
}

export function AuthLayout({ children, headline, subline, back }: AuthLayoutProps) {
  return (
    <div className="min-h-screen flex bg-white">
      <div className="hidden lg:flex lg:w-[46%] xl:w-[44%] shrink-0 flex-col h-screen sticky top-0 overflow-hidden p-10 xl:p-14"
        style={{ background: 'linear-gradient(150deg, #0F766E 0%, #115E59 55%, #134E4A 100%)' }}>
        <div aria-hidden="true" className="absolute -top-32 start-1/4 w-[480px] h-[480px] rounded-full blur-3xl pointer-events-none"
          style={{ background: 'rgba(94,234,212,.28)' }} />
        <div aria-hidden="true" className="absolute -bottom-40 -end-24 w-[480px] h-[480px] rounded-full blur-3xl pointer-events-none"
          style={{ background: 'rgba(167,139,250,.38)' }} />

        <Link href="/" aria-label="JobApply"
          className="relative w-fit rounded-xl bg-white px-3 py-2 shadow-elevation-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white">
          <Logo size={26} />
        </Link>

        <div className="relative flex-1 flex flex-col justify-center gap-10 min-h-0">
          <div>
            <h2 className="text-[44px] xl:text-[56px] leading-[1.05] font-extrabold tracking-[-0.035em] text-white [text-wrap:balance]">{headline}</h2>
            <p className="mt-5 max-w-md text-[17px] leading-relaxed text-teal-50/90">{subline}</p>
          </div>
          <PanelFeed />
        </div>
      </div>

      <div className="flex flex-1 min-w-0 flex-col">
        <header className="h-16 shrink-0 flex items-center justify-between gap-3 px-4 sm:px-10">
          <Link href={back.href} aria-label={back.aria}
            className="inline-flex items-center gap-1.5 min-h-[44px] px-1 text-[14px] font-medium text-slate-500 hover:text-slate-900 transition-colors">
            {/* Mirrored in RTL: "back" points toward the reading start. */}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="rtl:-scale-x-100">
              <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
            </svg>
            {back.label}
          </Link>
          <span className="lg:hidden"><Logo size={26} /></span>
          <LanguageSwitcher />
        </header>
        <main className="flex flex-1 justify-center px-5 sm:px-10 pt-4 pb-12 lg:items-center">
          {children}
        </main>
      </div>
    </div>
  )
}
