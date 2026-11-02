'use client'

import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import type { CvUploadStage } from '@/lib/api'
import { CheckIcon } from '@/components/icons'

// ── CvDropzone ───────────────────────────────────────────────────────────────
//
// Signup step 3, built around the same sheet of paper the welcome screen plays
// with: a small stack that fans out when a file is on its way, closes when it
// lands, and is read line by line while the server works. Processing takes
// 20-60s, so the wait has to look alive and say which step is running.
//
// The bar is an estimate: it eases toward 95% and never claims to be finished.
// The steps are what the server reports.

const STAGES: CvUploadStage[] = ['uploading', 'reading', 'analyzing']
const EXPECTED_S = 30
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'
const LINES = [100, 86, 100, 62, 92, 74]
// How many lines of the page count as read at each stage.
const READ: Record<CvUploadStage, number> = { uploading: 1, reading: 3, analyzing: 5 }

function Paper({ open, lift, busy, stage }: { open: boolean; lift: boolean; busy: boolean; stage: CvUploadStage }) {
  const sheet = (angle: number, x: number) => ({
    transform: busy ? 'none' : `translateX(${open ? x : 0}px) rotate(${open ? angle : 0}deg)`,
    transition: `transform 420ms ${EASE_OUT}`,
  })
  const fan = lift ? 1.9 : 1
  return (
    <div aria-hidden="true" className="relative w-[104px] h-[132px] pointer-events-none"
      style={{
        transform: lift ? 'translateY(-8px) scale(1.06)' : 'none',
        transition: `transform 420ms ${EASE_OUT}`,
      }}>
      <div className="absolute inset-0 rounded-xl bg-slate-50 border border-slate-200 origin-bottom" style={sheet(-6 * fan, -8 * fan)} />
      <div className="absolute inset-0 rounded-xl bg-slate-50 border border-slate-200 origin-bottom" style={sheet(6 * fan, 8 * fan)} />
      <div className="absolute inset-0 overflow-hidden rounded-xl bg-white border border-slate-200 shadow-elevation-2 px-3 py-3.5">
        <div className="h-2 w-3/5 rounded-full bg-slate-800/80" />
        <div className="mt-3 space-y-[7px]">
          {LINES.map((w, i) => (
            <div key={i} className="relative h-1.5 overflow-hidden rounded-full bg-slate-200" style={{ width: `${w}%` }}>
              <div className="absolute inset-0 bg-teal-500 origin-left rtl:origin-right"
                style={{
                  transform: busy && i < READ[stage] ? 'scaleX(1)' : 'scaleX(0)',
                  transition: `transform 600ms ${EASE_OUT} ${i * 90}ms`,
                }} />
            </div>
          ))}
        </div>
        {busy && (
          <div className="absolute inset-x-0 top-0 h-12 border-b-2 border-teal-500 animate-ja-scan motion-reduce:hidden"
            style={{ background: 'linear-gradient(to bottom, rgba(20,184,166,0), rgba(20,184,166,.2))' }} />
        )}
      </div>
      <span className="absolute -bottom-2.5 -end-2.5 grid w-9 h-9 place-items-center rounded-full bg-ja-primaryHover text-white shadow-elevation-2"
        style={{
          opacity: busy ? 0 : 1,
          transform: busy ? 'scale(.9)' : lift ? 'translateY(3px)' : 'none',
          transition: `opacity 200ms ${EASE_OUT}, transform 420ms ${EASE_OUT}`,
        }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 19V6" /><path d="m6 12 6-6 6 6" />
        </svg>
      </span>
    </div>
  )
}

function Progress({ stage }: { stage: CvUploadStage }) {
  const { t } = useI18n()
  const P = t.cv_progress
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 500)
    return () => clearInterval(id)
  }, [])
  const estimate = Math.min(0.95, 1 - Math.exp(-elapsed / EXPECTED_S))
  const current = STAGES.indexOf(stage)
  const labels: Record<CvUploadStage, string> = {
    uploading: P.step_uploading,
    reading:   P.step_reading,
    analyzing: P.step_analyzing,
  }
  return (
    <div role="status" aria-live="polite" className="mt-5 animate-ja-tab-in motion-reduce:animate-none">
      <div role="progressbar" aria-label={P.title} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(estimate * 100)}
        className="h-1 overflow-hidden rounded-full bg-slate-900/10">
        <div className="h-full bg-teal-600 origin-left rtl:origin-right"
          style={{ transform: `scaleX(${estimate})`, transition: 'transform 500ms linear' }} />
      </div>
      <ol className="mt-4 space-y-2.5">
        {STAGES.map((s, i) => {
          const done = i < current
          const on = i === current
          return (
            <li key={s} className={`flex items-center gap-3 text-[15px] transition-colors duration-ja-ui ${on ? 'font-semibold text-slate-900' : done ? 'text-slate-500' : 'text-slate-400'}`}>
              <span aria-hidden="true" className={`grid h-5 w-5 shrink-0 place-items-center rounded-full transition-colors duration-ja-ui ${done ? 'bg-teal-600 text-white' : on ? 'border-2 border-teal-600' : 'border border-slate-300'}`}>
                {done && <span className="animate-ja-tab-in motion-reduce:animate-none"><CheckIcon s={12} /></span>}
              </span>
              {labels[s]}
            </li>
          )
        })}
      </ol>
      <p className="mt-4 text-[14px] leading-relaxed text-slate-500">{P.hint}</p>
    </div>
  )
}

export function CvDropzone({ busy, stage, error, onFiles, onWrongType }: {
  busy:        boolean
  stage:       CvUploadStage
  error:       string
  onFiles:     (files: File[]) => void
  onWrongType: () => void
}) {
  const I = useI18n().t.onboarding.intake
  const input = useRef<HTMLInputElement>(null)
  const [names, setNames] = useState<string[]>([])
  const [dragging, setDragging] = useState(false)
  const [hovered, setHovered] = useState(false)
  // The stack fans out once on arrival, so the first thing the page does is move.
  const [arrived, setArrived] = useState(false)
  useEffect(() => {
    const id = setTimeout(() => setArrived(true), 180)
    return () => clearTimeout(id)
  }, [])

  const take = (files: File[]) => {
    if (!files.length) return
    setNames(files.map(f => f.name))
    onFiles(files)
  }

  return (
    <>
      <input ref={input} type="file" accept=".pdf,.docx" multiple className="hidden"
        onChange={e => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ''
          take(files)
        }} />
      {/* Keyed on the error so a second failure shakes it again. */}
      <button key={error} type="button" disabled={busy} onClick={() => input.current?.click()}
        onPointerEnter={e => { if (e.pointerType === 'mouse') setHovered(true) }}
        onPointerLeave={() => setHovered(false)}
        onDragOver={e => { e.preventDefault(); if (!busy) setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault()
          setDragging(false)
          if (busy) return
          const all = Array.from(e.dataTransfer.files)
          const usable = all.filter(f => /\.(pdf|docx)$/i.test(f.name))
          if (all.length && !usable.length) onWrongType()
          take(usable)
        }}
        className={`mt-8 w-full flex flex-col items-center gap-6 rounded-[28px] px-6 pt-10 pb-8 text-center ring-inset shadow-elevation-2 backdrop-blur-xl [@media(prefers-reduced-transparency:reduce)]:bg-white transition-[background-color,box-shadow,transform] duration-ja-ui active:scale-[0.99] active:duration-ja-press focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 disabled:active:scale-100 ${
          error ? 'animate-ja-shake motion-reduce:animate-none' : ''
        } ${
          busy ? 'ring-1 ring-slate-900/5 bg-white/50'
            : dragging ? 'ring-2 ring-teal-600 bg-teal-50/80 scale-[1.015]'
            : hovered ? 'ring-1 ring-teal-600/40 bg-white/90'
            : 'ring-1 ring-slate-900/5 bg-white/60'
        }`}>
        <Paper open={arrived} lift={dragging || hovered} busy={busy} stage={stage} />
        <span key={busy ? 'busy' : dragging ? 'drag' : 'idle'} className="block min-w-0 max-w-full pointer-events-none animate-ja-tab-in motion-reduce:animate-none">
          {busy ? (
            <>
              <span dir="auto" className="block truncate text-[18px] font-semibold tracking-tight text-slate-900">
                {names.length === 1 ? names[0] : I.files_count.replace('{n}', String(names.length))}
              </span>
              <span className="block mt-1 text-[15px] text-slate-600">{I.reading}</span>
            </>
          ) : (
            <>
              <span className="block text-[18px] font-semibold tracking-tight text-slate-900">{dragging ? I.drag_over : I.upload_cta}</span>
              <span className="block mt-1 text-[15px] leading-relaxed text-slate-600">{I.upload_hint}</span>
            </>
          )}
        </span>
      </button>

      {busy && <Progress stage={stage} />}
      {error && <p className="mt-3 text-[14px] text-rose-600" role="alert">{error}</p>}
    </>
  )
}
