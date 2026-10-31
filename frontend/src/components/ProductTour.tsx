'use client'

import { useCallback, useEffect, useLayoutEffect, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import { useAuth } from '@/contexts/AuthContext'
import type { User } from '@supabase/supabase-js'
import { TOKENS } from '@/lib/tokens'

// First-visit tour. A tester asked for "an explanation that pops up the first
// time, showing the main things to notice and where to start". Four short
// steps over the overview, each lighting up one real element (looked up by
// its data-tour attribute) with two lines of copy. Shown once; replayable
// from the user menu, which dispatches TOUR_REPLAY_EVENT.
//
// "Shown once" is stored on the account (user_metadata.tour_done), not only
// in this browser: signOut() clears localStorage, so the browser flag alone
// brought the tour back after every login and on every new device.
//
// The card sits at the bottom of the screen rather than beside the target:
// it never covers what it describes, and it behaves the same on a phone.

export const TOUR_DONE_KEY     = 'ja.tour_done'
export const TOUR_REPLAY_EVENT = 'ja:tour-replay'

const TARGETS: (string | null)[] = [null, 'top-matches', 'confidence', 'ariel']

function readDone(user: User | null): boolean {
  if ((user?.user_metadata as Record<string, unknown> | undefined)?.tour_done === true) return true
  try { return window.localStorage.getItem(TOUR_DONE_KEY) === '1' } catch { return true }
}
function markDone(): void {
  try { window.localStorage.setItem(TOUR_DONE_KEY, '1') } catch { /* private mode */ }
}

export function isTourPending(user: User | null): boolean {
  return typeof window !== 'undefined' && !readDone(user)
}

export function ProductTour({ ready }: { ready: boolean }) {
  const T = useI18n().t.tour
  const { user, updateUserMeta } = useAuth()
  const [step, setStep] = useState<number | null>(null)
  const [rect, setRect] = useState<DOMRect | null>(null)

  // Start once the overview has rendered its sections.
  useEffect(() => {
    if (!ready || readDone(user)) return
    const id = setTimeout(() => setStep(0), 800)
    return () => clearTimeout(id)
  }, [ready, user])

  useEffect(() => {
    const replay = () => setStep(0)
    window.addEventListener(TOUR_REPLAY_EVENT, replay)
    return () => window.removeEventListener(TOUR_REPLAY_EVENT, replay)
  }, [])

  const finish = useCallback(() => {
    markDone()
    void updateUserMeta({ tour_done: true }).catch(() => { /* the browser flag still holds */ })
    setStep(null)
    setRect(null)
  }, [updateUserMeta])

  // Track the current target: scroll it into view, then follow it through
  // scrolling and resizing. A missing target (e.g. no matches yet) just
  // means that step shows without a highlight.
  useLayoutEffect(() => {
    if (step === null) return
    const key = TARGETS[step]
    const el = key ? document.querySelector<HTMLElement>(`[data-tour="${key}"]`) : null
    if (!el) { setRect(null); return }
    // Near the top (below the sticky header), leaving the lower part of the
    // screen to the explanation card.
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth' })
    const update = () => setRect(el.getBoundingClientRect())
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    const settle = setTimeout(update, 450)
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
      clearTimeout(settle)
    }
  }, [step])

  useEffect(() => {
    if (step === null) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') finish() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step, finish])

  if (step === null) return null
  const s = T.steps[step]
  const last = step === T.steps.length - 1
  const pad = 8

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-labelledby="ja-tour-title">
      {/* Dim everything; with a target, cut a lit window around it. */}
      {rect ? (
        <div
          aria-hidden
          className="fixed rounded-2xl pointer-events-none transition-all duration-300"
          style={{
            top: rect.top - pad, left: rect.left - pad,
            width: rect.width + pad * 2, height: rect.height + pad * 2,
            boxShadow: '0 0 0 9999px rgba(15,23,42,0.55)',
          }}
        />
      ) : (
        <div aria-hidden className="fixed inset-0 bg-slate-900/55" />
      )}

      <div
        className="fixed inset-x-4 sm:inset-x-auto sm:start-1/2 sm:w-[26rem] sm:rtl:translate-x-1/2 sm:ltr:-translate-x-1/2 bottom-[calc(1rem+env(safe-area-inset-bottom))] rounded-2xl bg-white p-5 text-start"
        style={{ boxShadow: '0 20px 50px rgba(15,23,42,0.30)' }}
      >
        <p className="text-[11.5px] font-medium text-slate-400">
          {T.step_of.replace('{n}', String(step + 1)).replace('{total}', String(T.steps.length))}
        </p>
        <h2 id="ja-tour-title" className="mt-1 text-[16px] font-bold text-slate-900 leading-snug">{s.title}</h2>
        <p className="mt-1.5 text-[13.5px] text-slate-600 leading-relaxed">{s.body}</p>

        <div className="mt-4 flex items-center gap-2">
          <button
            onClick={() => (last ? finish() : setStep(step + 1))}
            autoFocus
            className="h-11 sm:h-9 px-5 rounded-lg text-[13.5px] font-semibold text-white"
            style={{ background: TOKENS.color.primary }}
          >
            {last ? T.done : T.next}
          </button>
          {step > 0 && (
            <button
              onClick={() => setStep(step - 1)}
              className="h-11 sm:h-9 px-3 rounded-lg text-[13px] font-medium text-slate-600 hover:bg-slate-50"
            >
              {T.back}
            </button>
          )}
          {!last && (
            <button
              onClick={finish}
              className="ms-auto h-11 sm:h-9 px-3 rounded-lg text-[13px] font-medium text-slate-400 hover:text-slate-600"
            >
              {T.skip}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
