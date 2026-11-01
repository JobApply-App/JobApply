'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useI18n } from '@/contexts/I18nContext'

// Most users open JobApply on a phone, where the main sections sat behind the
// hamburger — two taps and a hidden menu for every switch. This bar keeps the
// four sections people actually move between one thumb-tap away. Everything
// else (all jobs, analytics, language) stays in the hamburger panel.
//
// It is fixed to the bottom, so the page needs room underneath: while mounted
// it marks <body> with `has-tabbar`, which globals.css pads on small screens.
// The Ariel launcher reads the same class to sit above the bar.

type Item = { key: 'overview' | 'feed' | 'apps' | 'capabilities'; href: string; icon: JSX.Element }

const s = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

const ITEMS: Item[] = [
  { key: 'overview', href: '/?tab=overview', icon: <svg {...s}><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" /></svg> },
  { key: 'feed', href: '/?tab=feed', icon: <svg {...s}><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg> },
  { key: 'apps', href: '/?tab=apps', icon: <svg {...s}><path d="M9 11l3 3 8-8" /><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9" /></svg> },
  { key: 'capabilities', href: '/capabilities', icon: <svg {...s}><path d="M12 2l3 6.5 7 .9-5.2 4.8 1.4 6.9L12 17.8 5.8 21.1l1.4-6.9L2 9.4l7-.9z" /></svg> },
]

export function MobileTabBar({ tab, onTab }: { tab?: string | null; onTab?: (t: 'overview' | 'feed' | 'apps') => void }) {
  const H = useI18n().t.header
  const pathname = usePathname()

  useEffect(() => {
    document.body.classList.add('has-tabbar')
    return () => document.body.classList.remove('has-tabbar')
  }, [])

  const current =
    pathname === '/capabilities' ? 'capabilities'
    : pathname === '/' ? (tab ?? 'overview')
    : null

  return (
    <nav
      aria-label={H.mobile_tabs_label}
      className="md:hidden fixed inset-x-0 bottom-0 z-40 ja-glass border-t border-slate-200/70"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <ul className="grid grid-cols-4">
        {ITEMS.map(item => {
          const active = current === item.key
          return (
            <li key={item.key}>
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                onClick={() => {
                  if (item.key !== 'capabilities' && pathname === '/') onTab?.(item.key)
                }}
                className={`ja-press flex flex-col items-center justify-center gap-0.5 h-16 text-[11.5px] font-medium transition-colors duration-ja-ui ${
                  active ? 'text-teal-700' : 'text-slate-500 active:text-slate-800'
                }`}
              >
                {/* The highlight is always there and grows in from the icon's
                    centre when the tab becomes active, so a switch reads as
                    the bar answering the tap rather than a box appearing. */}
                <span className="relative inline-flex items-center justify-center h-7 w-12">
                  <span
                    aria-hidden
                    className={`absolute inset-0 rounded-lg bg-teal-50 transition-[transform,opacity] duration-ja-ui ${
                      active ? 'opacity-100 scale-100' : 'opacity-0 scale-x-50'
                    }`}
                  />
                  <span className="relative">{item.icon}</span>
                </span>
                {H.nav[item.key]}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
