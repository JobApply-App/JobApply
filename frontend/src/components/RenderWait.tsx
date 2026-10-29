'use client'

import { useEffect, useRef, useState } from 'react'
import { fetchRenderQueue, type RenderQueueStatus } from '@/lib/api'
import { waitView } from '@/lib/pdfQueue'
import { useI18n } from '@/contexts/I18nContext'

/**
 * Live wait indicator for a pending PDF render.
 *
 * The server renders one PDF at a time, so under load a render can wait its
 * turn. A frozen spinner makes people leave; this shows how long is left
 * ("ready in about 4 seconds", or "2 CVs ahead of you") with a bar that only
 * moves forward. It polls /api/resumes/render-queue once a second while
 * `active`, and ticks the countdown locally in between so it moves smoothly.
 */
export function RenderWait({ active, compact = false }: { active: boolean; compact?: boolean }) {
  const A = useI18n().t.applier
  const [status, setStatus] = useState<RenderQueueStatus | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const startedAt = useRef(Date.now())
  const progressRef = useRef(0)
  const polledAt = useRef(Date.now())

  useEffect(() => {
    if (!active) return
    startedAt.current = Date.now()
    progressRef.current = 0
    setStatus(null)
    let alive = true
    const poll = () => fetchRenderQueue().then(s => {
      if (alive) { polledAt.current = Date.now(); setStatus(s) }
    }).catch(() => {})
    poll()
    const pollId = setInterval(poll, 1000)
    const tickId = setInterval(() => setNow(Date.now()), 250)
    return () => { alive = false; clearInterval(pollId); clearInterval(tickId) }
  }, [active])

  if (!active) return null

  const elapsed = (now - startedAt.current) / 1000
  const view = waitView(status, (now - polledAt.current) / 1000, elapsed, progressRef.current)
  progressRef.current = view.progress
  const label =
    view.kind === 'queue'  ? A.render_wait_queue.replace('{n}', String(view.ahead)).replace('{s}', String(view.seconds)) :
    view.kind === 'eta'    ? A.render_wait_eta.replace('{s}', String(view.seconds)) :
    A.render_wait_almost

  return (
    <div role="status" aria-live="polite" className={compact ? 'w-full max-w-[240px]' : 'w-full max-w-[320px] px-6'}>
      <p className={`${compact ? 'text-[11.5px]' : 'text-[13px]'} font-medium text-slate-600 text-center mb-2`}>
        {label}
      </p>
      <div
        className="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(view.progress * 100)}
      >
        <div
          className="h-full rounded-full bg-teal-600 transition-[width] duration-300 ease-out"
          style={{ width: `${Math.max(4, view.progress * 100)}%` }}
        />
      </div>
    </div>
  )
}
