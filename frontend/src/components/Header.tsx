'use client'
import { useState, useEffect, useLayoutEffect, useRef } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { useI18n } from '@/contexts/I18nContext'
import { TOKENS } from '@/lib/tokens'
import { Logo } from './ui/Logo'
import { StatusDot } from './ui/StatusDot'
import { BellIcon, SlidersIcon, ChevIcon, MenuIcon, XIcon, SparkIcon } from './icons'
import { LanguageSwitcher } from './LanguageSwitcher'
import { MobileTabBar } from './MobileTabBar'
import { TOUR_DONE_KEY, TOUR_REPLAY_EVENT } from './ProductTour'
import { useAuth } from '@/contexts/AuthContext'
import { useChat } from '@/contexts/ChatContext'
import { resolveDisplayName, getInitials } from '@/lib/nameUtils'
import type { Job } from '@/lib/data'

function HelpIcon({ s = 15 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

export type Tab = 'overview' | 'apps' | 'feed' | 'all-jobs'

const TABS: { id: Tab }[] = [
  // ids are route keys and stay in code; labels come from header.nav.
  { id: 'overview' },
  { id: 'feed'     },
  { id: 'apps'     },
  { id: 'all-jobs' },
]

interface HeaderProps {
  tab?:            Tab
  setTab?:         (t: Tab) => void
  onOpenControls?: () => void
  jobs?:           Job[]
}

export function Header({ tab, setTab, onOpenControls, jobs = [] }: HeaderProps) {
  const { t: _t } = useI18n()
  const H = _t.header
  const TR = _t.tour
  const [menuOpen,       setMenuOpen]       = useState(false)
  const [bellOpen,       setBellOpen]       = useState(false)
  const [mobileNavOpen,  setMobileNavOpen]  = useState(false)
  const router    = useRouter()
  const pathname  = usePathname()
  const bellRef   = useRef<HTMLDivElement>(null)
  const menuRef   = useRef<HTMLDivElement>(null)

  const { user, signOut } = useAuth()
  const { openEliya, isEliyaOpen } = useChat()
  const displayName = resolveDisplayName(user?.email, user?.user_metadata as Record<string, unknown> | null)
  const initials    = getInitials(displayName)

  const highMatchJobs = jobs.filter(j => j.score >= 85)
  const hasHighMatch  = highMatchJobs.length > 0

  // Close bell dropdown on outside tap/click ('mousedown' also fires from a
  // tap on every mobile browser, so this works for touch and mouse alike).
  useEffect(() => {
    if (!bellOpen) return
    function handleClickOutside(e: MouseEvent) {
      if (bellRef.current && !bellRef.current.contains(e.target as Node)) {
        setBellOpen(false)
      }
    }
    function handleEscape(e: KeyboardEvent) { if (e.key === 'Escape') setBellOpen(false) }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [bellOpen])

  // Close user menu on outside tap/click. Previously this used onMouseLeave,
  // which never fires on touch devices — the menu could get stuck open on
  // mobile. Same click-outside pattern as the bell dropdown above.
  useEffect(() => {
    if (!menuOpen) return
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    function handleEscape(e: KeyboardEvent) { if (e.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [menuOpen])

  // Close the mobile nav panel on route/tab change so it never lingers open
  // after navigating.
  useEffect(() => { setMobileNavOpen(false) }, [pathname, tab])

  // ── Optimistic active-tab indicator (JOB-112) ─────────────────────────────
  // Capabilities/Analytics are real route navigations (<Link>, not client tab
  // state), so `onAnalytics`/`onCapabilities` below were derived purely from
  // `pathname` — which only updates once the destination page's own Header
  // instance has actually mounted. Between the click and that mount (an RSC
  // fetch + render, not instant even on a fast connection), the clicked link
  // shows no visual change at all: no pressed state, no underline movement,
  // nothing. That silent gap is what reads as "the click didn't register" —
  // confirmed by testing that a single click always DOES navigate, just not
  // synchronously, which nothing in the UI communicated in the meantime,
  // making a second (redundant but harmless) click feel necessary.
  // `pendingNav` flips the indicator the instant the link is clicked; once
  // the real navigation lands, `pathname` itself matches and this resets.
  const [pendingNav, setPendingNav] = useState<'analytics' | 'capabilities' | null>(null)
  useEffect(() => { setPendingNav(null) }, [pathname])

  // Suppress tab underlines on any route that isn't the main dashboard.
  const onMainDashboard   = pathname === '/'
  const onAnalytics       = pathname === '/analytics'    || pendingNav === 'analytics'
  const onCapabilities    = pathname === '/capabilities' || pendingNav === 'capabilities'
  const activeTab         = onMainDashboard ? (tab ?? null) : null

  // One underline that slides to the active item, instead of a border that
  // blinks off one item and on another. Measured from the items themselves,
  // so it fits each label in either language; moved with transform only.
  const navRef = useRef<HTMLElement>(null)
  const activeNav = onCapabilities ? 'capabilities' : onAnalytics ? 'analytics' : activeTab
  const [bar, setBar] = useState<{ x: number; w: number } | null>(null)
  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const place = () => {
      const el = activeNav ? nav.querySelector<HTMLElement>(`[data-nav="${activeNav}"]`) : null
      if (!el) { setBar(null); return }
      const n = nav.getBoundingClientRect(), r = el.getBoundingClientRect()
      setBar({ x: r.left - n.left, w: r.width })
    }
    place()
    const ro = new ResizeObserver(place)
    ro.observe(nav)
    return () => ro.disconnect()
  }, [activeNav, H])

  const navItem = (active: boolean) =>
    `ja-press h-full inline-flex items-center transition-colors duration-ja-ui ${
      active ? 'text-slate-900' : 'hover:text-slate-900'
    }`

  const goToTab = (t: Tab) => {
    // Encode the tab in the URL so it survives any auth-cycle redirect.
    // searchParams.get('tab') has priority over localStorage in page.tsx,
    // so even if localStorage is wiped by _onAuthError the user lands back
    // on the correct tab rather than defaulting to 'overview'.
    router.push(`/?tab=${t}`)
    setTab?.(t)
  }

  return (
    <>
    <header className="w-full ja-glass border-b border-slate-100/70 sticky top-0 z-40">
      <div className="max-w-[1920px] mx-auto px-4 sm:px-6 lg:px-12 h-14 md:h-[60px] grid grid-cols-[auto_1fr_auto] items-center gap-3 md:gap-8">

      <div className="flex items-center gap-1">
        {/* Hamburger — mobile/tablet only, opens the stacked nav panel below */}
        <button
          onClick={() => setMobileNavOpen(v => !v)}
          aria-label={mobileNavOpen ? H.close_menu : H.open_menu}
          aria-expanded={mobileNavOpen}
          className="md:hidden inline-flex items-center justify-center w-11 h-11 -ml-2 rounded-lg text-slate-500 active:bg-slate-100 transition-colors"
        >
          {mobileNavOpen ? <XIcon s={18} /> : <MenuIcon s={18} />}
        </button>
        <Logo />
      </div>

      {/* Primary nav — desktop/tablet only, centered, text-only with bottom-border active indicator */}
      <nav ref={navRef} className="relative hidden md:flex items-center justify-center gap-10 text-sm font-medium text-slate-500 h-full">
        {TABS.map(t => (
          <button
            key={t.id}
            data-nav={t.id}
            onClick={() => goToTab(t.id)}
            aria-current={activeTab === t.id ? 'page' : undefined}
            className={navItem(activeTab === t.id)}
          >
            {H.nav[t.id === 'all-jobs' ? 'all_jobs' : t.id]}
          </button>
        ))}
        <Link
          href="/capabilities"
          data-nav="capabilities"
          onClick={() => setPendingNav('capabilities')}
          aria-current={onCapabilities ? 'page' : undefined}
          className={navItem(onCapabilities)}
        >
          {H.nav.capabilities}
        </Link>
        <Link
          href="/analytics"
          data-nav="analytics"
          onClick={() => setPendingNav('analytics')}
          aria-current={onAnalytics ? 'page' : undefined}
          className={navItem(onAnalytics)}
        >
          {H.nav.analytics}
        </Link>
        <span
          aria-hidden
          className="pointer-events-none absolute bottom-0 left-0 h-0.5 w-px origin-left rounded-full bg-slate-900 transition-[transform,opacity] duration-ja-ui"
          style={{
            transform: `translateX(${bar?.x ?? 0}px) scaleX(${bar?.w ?? 0})`,
            opacity: bar ? 1 : 0,
          }}
        />
      </nav>

      {/* Right-side utility cluster */}
      <div className="flex items-center gap-1 sm:gap-3 justify-end">
        {/* Always rendered (just hidden off-feed) rather than conditionally
            mounted — this cluster sits in the grid's `auto`-sized right
            track, and the center nav lives in the adjacent `1fr` track. If
            this button's presence toggled the track's rendered width, the
            centered nav would visibly shift left/right on every tab switch
            that crosses the feed boundary. `invisible` keeps the layout slot
            reserved without showing or allowing interaction with it. */}
        {(() => {
          const showPreferences = pathname === '/' && tab === 'feed' && Boolean(onOpenControls)
          return (
            <button
              onClick={() => onOpenControls?.()}
              aria-hidden={!showPreferences}
              tabIndex={showPreferences ? 0 : -1}
              className={`inline-flex items-center gap-1.5 h-11 sm:h-7 px-3 rounded-md text-[12.5px] font-medium text-slate-500 active:bg-slate-100 sm:hover:text-slate-800 sm:hover:bg-slate-50 border border-slate-200 transition-colors ${
                showPreferences ? '' : 'invisible pointer-events-none'
              }`}
            >
              <SlidersIcon s={14} /> <span className="hidden sm:inline">{H.preferences}</span>
            </button>
          )
        })()}

        {/* Interface language. In the header rather than behind a settings
            screen so it can be changed from anywhere, at any point — a user
            who ends up in a language they cannot read should not have to
            navigate a menu written in that language to get out. Hidden on
            the narrowest widths, where it appears in the mobile drawer
            instead so it is never simply unavailable. */}
        <LanguageSwitcher className="hidden sm:inline-flex" />

        {/* Help — opens Eliya support chat (indigo theme). Color is driven purely
            by isEliyaOpen state; the hover tint is a plain Tailwind :hover class,
            not imperative JS — so it's a harmless desktop-only enhancement rather
            than something the interaction depends on. */}
        <button
          onClick={openEliya}
          title={H.help_title}
          aria-label={H.help_label}
          className={`ja-press inline-flex items-center justify-center w-11 h-11 sm:w-8 sm:h-8 rounded-md transition-colors ${
            isEliyaOpen
              ? 'text-indigo-600 bg-indigo-50'
              : 'text-slate-400 active:bg-slate-100 sm:hover:text-indigo-600 sm:hover:bg-indigo-50'
          }`}
        >
          <HelpIcon s={16} />
        </button>

        {/* Bell */}
        <div className="relative" ref={bellRef}>
          <button
            onClick={() => { setMenuOpen(false); setBellOpen(v => !v) }}
            title={H.notifications}
            aria-label={H.notifications}
            aria-haspopup="true"
            aria-expanded={bellOpen}
            className="ja-press inline-flex items-center justify-center w-11 h-11 sm:w-8 sm:h-8 rounded-md text-slate-500 active:bg-slate-100 sm:hover:text-slate-700 sm:hover:bg-slate-50 transition-colors"
          >
            <BellIcon s={16} />
          </button>
          {hasHighMatch && (
            <span className="absolute top-1.5 end-1.5 sm:top-1 sm:end-1 w-1.5 h-1.5 rounded-full bg-rose-500 ring-2 ring-white pointer-events-none" />
          )}

          {bellOpen && (
            <div
              className="absolute end-0 top-12 sm:top-11 w-72 max-w-[calc(100vw-2rem)] rounded-xl bg-white/85 backdrop-blur-xl border border-white/60 shadow-floating overflow-hidden z-50 animate-ja-menu-in origin-top-right rtl:origin-top-left"
            >
              <div className="px-3 py-2.5 border-b border-slate-50 flex items-center justify-between">
                <span className="text-[12px] font-semibold text-slate-700">{H.alerts_title}</span>
                {highMatchJobs.length > 0 && (
                  <span className="text-[10.5px] font-semibold text-rose-600 bg-rose-50 border border-rose-200 px-1.5 py-0.5 rounded-md">
                    {highMatchJobs.length}
                  </span>
                )}
              </div>
              {highMatchJobs.length === 0 ? (
                <p className="px-3 py-4 text-[12.5px] text-slate-500 text-center">
                  {H.alerts_empty}
                </p>
              ) : (
                <ul className="max-h-72 overflow-y-auto divide-y divide-slate-50">
                  {highMatchJobs.map(job => (
                    <li key={job.id}>
                      <button
                        onClick={() => setBellOpen(false)}
                        className="w-full text-start px-3 py-2.5 active:bg-slate-100 sm:hover:bg-slate-50 transition-colors flex items-center justify-between gap-3"
                      >
                        <div className="min-w-0">
                          <p className="text-[12.5px] font-semibold text-slate-900 truncate">{job.title}</p>
                          <p className="text-[11.5px] text-slate-500 truncate">{job.company}</p>
                        </div>
                        <span className="shrink-0 text-[11.5px] font-bold tabular-nums px-2 py-0.5 rounded-lg bg-teal-50 text-teal-700">
                          {job.score.toFixed(1)}%
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {/* User avatar + menu */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => { setBellOpen(false); setMenuOpen(v => !v) }}
            aria-label={displayName}
            aria-haspopup="true"
            aria-expanded={menuOpen}
            className="ja-press w-11 h-11 sm:w-8 sm:h-8 rounded-md bg-slate-100 text-slate-600 flex items-center justify-center text-xs font-bold active:bg-slate-200 sm:hover:bg-slate-200 transition-colors"
          >
            {initials}
          </button>

          {menuOpen && (
            <div
              className="absolute end-0 top-12 sm:top-10 w-56 rounded-xl bg-white/85 backdrop-blur-xl border border-white/60 shadow-floating overflow-hidden z-50 animate-ja-menu-in origin-top-right rtl:origin-top-left"
            >
              <div className="px-3 py-3 border-b border-slate-50">
                <div className="text-[13px] font-semibold text-slate-900">{displayName}</div>
                <div className="text-[12px] text-slate-500 truncate">{user?.email ?? ''}</div>
              </div>
              <button
                onClick={() => { setMenuOpen(false); router.push('/profile-builder') }}
                className="w-full text-start px-3 py-2.5 text-[13px] font-semibold flex items-center gap-2 active:bg-violet-100 sm:hover:bg-violet-50 text-violet-700 border-b border-slate-50 transition-colors"
              >
                <SparkIcon s={15} />
                {H.profile_builder}
              </button>
              {/* Had no onClick — tapping it did nothing. Preferences live in
                  the controls sheet on the matches tab. */}
              <button
                onClick={() => {
                  setMenuOpen(false)
                  if (onOpenControls && pathname === '/') { goToTab('feed'); onOpenControls() }
                  else router.push('/?tab=feed')
                }}
                className="w-full text-start px-3 py-2 text-[13px] text-slate-700 active:bg-slate-100 sm:hover:bg-slate-50 transition-colors"
              >
                {H.profile_prefs}
              </button>
              <button
                onClick={() => {
                  setMenuOpen(false)
                  try { window.localStorage.removeItem(TOUR_DONE_KEY) } catch { /* private mode */ }
                  window.dispatchEvent(new Event(TOUR_REPLAY_EVENT))
                  goToTab('overview')
                }}
                className="w-full text-start px-3 py-2 text-[13px] text-slate-700 active:bg-slate-100 sm:hover:bg-slate-50 transition-colors"
              >
                {TR.replay}
              </button>
              <div className="border-t border-slate-200" />
              {process.env.NODE_ENV === 'development' && (
                <button
                  onClick={async () => {
                    setMenuOpen(false)
                    await signOut()
                  }}
                  className="w-full text-start px-3 py-2 text-[11.5px] font-mono text-amber-700 active:bg-amber-100 sm:hover:bg-amber-50 transition-colors flex items-center gap-1.5"
                  title={H.force_reset_title}
                >
                  <span className="text-[10px] bg-amber-100 text-amber-600 font-bold px-1 rounded">DEV</span>
                  {H.force_reset}
                </button>
              )}
              <button
                onClick={() => { setMenuOpen(false); void signOut() }}
                className="w-full text-start px-3 py-2 text-[13px] text-rose-600 active:bg-rose-100 sm:hover:bg-rose-50 transition-colors"
              >
                {H.sign_out}
              </button>
            </div>
          )}
        </div>
      </div>

      </div>

      {/* ── Mobile nav panel — boxless stacked list, replaces the hidden desktop nav.
          Tap-only: no hover states needed since every row is a full-width button. */}
      {mobileNavOpen && (
        <nav className="md:hidden border-t border-slate-100 px-4 py-2 animate-ja-menu-in origin-top">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => goToTab(t.id)}
              className={`w-full text-start h-11 px-2 rounded-lg text-[14px] font-medium flex items-center transition-colors ${
                activeTab === t.id
                  ? 'text-teal-700 bg-teal-50'
                  : 'text-slate-600 active:bg-slate-50'
              }`}
            >
              {H.nav[t.id === 'all-jobs' ? 'all_jobs' : t.id]}
            </button>
          ))}
          <Link
            href="/capabilities"
            onClick={() => setPendingNav('capabilities')}
            className={`w-full text-start h-11 px-2 rounded-lg text-[14px] font-medium flex items-center transition-colors ${
              onCapabilities ? 'text-teal-700 bg-teal-50' : 'text-slate-600 active:bg-slate-50'
            }`}
          >
            {H.nav.capabilities}
          </Link>
          <Link
            href="/analytics"
            onClick={() => setPendingNav('analytics')}
            className={`w-full text-start h-11 px-2 rounded-lg text-[14px] font-medium flex items-center transition-colors ${
              onAnalytics ? 'text-teal-700 bg-teal-50' : 'text-slate-600 active:bg-slate-50'
            }`}
          >
            {H.nav.analytics}
          </Link>
          {/* Same control as the desktop header, which is hidden below `sm`. */}
          <div className="pt-2 mt-1 border-t border-slate-100">
            <LanguageSwitcher className="w-full justify-center" />
          </div>
        </nav>
      )}
    </header>
    <MobileTabBar tab={activeTab} onTab={t => setTab?.(t)} />
    </>
  )
}
