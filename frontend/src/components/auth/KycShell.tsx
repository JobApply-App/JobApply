'use client'

import Link from 'next/link'
import { useI18n } from '@/contexts/I18nContext'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { Logo } from '@/components/ui/Logo'

// ── KycShell ─────────────────────────────────────────────────────────────────
//
// The canvas every signup step stands on: one light surface with a soft glow
// behind it, no split panel, a translucent bar that scrolls content under it and
// a single line of progress. `aside` is what the step shows beside the question
// (the career card, the welcome scene); on a phone it comes first.
//
// Rendered at the same place by each onboarding step, so the card and the
// progress line stay mounted and carry on between steps instead of restarting.

const GLOW = [
  'radial-gradient(58% 52% at 84% 22%, rgba(94,234,212,.5), transparent 72%)',
  'radial-gradient(44% 48% at 68% 88%, rgba(167,139,250,.3), transparent 72%)',
  'radial-gradient(46% 40% at 8% 2%, rgba(204,251,241,.8), transparent 72%)',
].join(',')

export function KycShell({ children, aside, caption, step, progress, back, headerEnd }: {
  children:   React.ReactNode
  aside:      React.ReactNode
  /** Under the aside, on wide screens only. */
  caption?:   { headline: string; subline: string }
  /** Which of the three signup steps this is. Omitted for someone already through signup. */
  step?:      1 | 2 | 3
  /** 0 to 1. Omitted where there is nothing to measure (the welcome screen). */
  progress?:  number
  /** The way back: `label` is shown, `aria` says where it goes. */
  back?:      { href: string; label: string; aria: string }
  /** Beside the language menu, for someone already signed in (Sign out). */
  headerEnd?: React.ReactNode
}) {
  const S = useI18n().t.signup.steps
  const stepText = step && S.label
    .replace('{n}', String(step))
    .replace('{total}', String(S.names.length))
    .replace('{name}', S.names[step - 1])

  return (
    <div className="relative isolate min-h-[100dvh] bg-slate-50">
      <div aria-hidden="true" className="fixed inset-0 -z-10 pointer-events-none rtl:-scale-x-100" style={{ background: GLOW }} />

      <header className="sticky top-0 z-20 bg-white/60 backdrop-blur-xl [@media(prefers-reduced-transparency:reduce)]:bg-white">
        <div className="mx-auto max-w-[1200px] h-16 flex items-center justify-between gap-3 px-5 sm:px-10">
          <Link href="/" aria-label="JobApply" className="shrink-0 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600">
            <Logo size={26} />
          </Link>
          {stepText && <p className="hidden md:block text-[14px] text-slate-600">{stepText}</p>}
          <div className="flex items-center gap-1 sm:gap-2">
            <LanguageSwitcher />
            {headerEnd}
          </div>
        </div>
        <div aria-hidden="true" className="h-0.5 bg-slate-900/5">
          {progress !== undefined && (
            <div className="h-full bg-ja-primaryHover origin-left rtl:origin-right transition-transform duration-[500ms] ease-ja-out motion-reduce:transition-none"
              style={{ transform: `scaleX(${progress})` }} />
          )}
        </div>
      </header>
      {stepText && <p className="sr-only md:hidden">{stepText}</p>}

      <div className="mx-auto max-w-[1200px] grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-16 xl:gap-x-24 px-5 sm:px-10 lg:min-h-[calc(100dvh-66px)]">
        <aside className="min-w-0 max-lg:pt-5 lg:order-2 lg:sticky lg:self-start lg:top-[max(96px,calc(50vh-250px))]">
          {aside}
          {caption && (
            <div className="hidden lg:block mt-8 max-w-[440px]">
              <p className="text-[20px] leading-snug font-semibold tracking-tight text-slate-900">{caption.headline}</p>
              <p className="mt-1.5 text-[15px] leading-relaxed text-slate-600">{caption.subline}</p>
            </div>
          )}
        </aside>

        <main className="min-w-0 w-full max-w-[520px] pt-6 pb-10 lg:self-center lg:py-12">
          {back && (
            <Link href={back.href} aria-label={back.aria}
              className="-ms-1 mb-4 inline-flex items-center gap-1.5 min-h-[44px] px-1 rounded-lg text-[14px] font-medium text-slate-600 hover:text-slate-900 transition-colors duration-ja-ui focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600">
              {/* Mirrored in RTL: "back" points toward the reading start. */}
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="rtl:-scale-x-100">
                <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
              </svg>
              {back.label}
            </Link>
          )}
          {children}
        </main>
      </div>
    </div>
  )
}
