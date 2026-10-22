'use client'

import { useEffect, useState } from 'react'
import { useI18n } from '@/contexts/I18nContext'
import type { CvUploadStage } from '@/lib/api'
import { CheckIcon } from './icons'

// CV processing takes 20-60s. A lone spinner for that long read to testers
// as "stuck", and some uploaded again. This shows which step is running
// (reported by the server) and a bar that moves with elapsed time. The bar
// is an estimate — it eases toward 95% and never claims to be finished.

const STEPS: CvUploadStage[] = ['uploading', 'reading', 'analyzing']
const EXPECTED_S = 30

export function CvUploadProgress({ stage }: { stage: CvUploadStage }) {
  const P = useI18n().t.cv_progress
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = Date.now()
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 500)
    return () => clearInterval(id)
  }, [])

  const pct = Math.round(Math.min(95, 100 * (1 - Math.exp(-elapsed / EXPECTED_S))))
  const current = STEPS.indexOf(stage)
  const label: Record<CvUploadStage, string> = {
    uploading: P.step_uploading,
    reading:   P.step_reading,
    analyzing: P.step_analyzing,
  }

  return (
    <div className="mt-3 rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-3.5 text-start" role="status" aria-live="polite">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-semibold text-slate-800">{P.title}</span>
        <span className="text-[12px] tabular-nums text-slate-400">{pct}%</span>
      </div>
      <div
        className="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={P.title}
      >
        <div className="h-full rounded-full bg-teal-500 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <ol className="mt-3 space-y-1.5">
        {STEPS.map((step, i) => {
          const done = i < current
          const active = i === current
          return (
            <li key={step} className="flex items-center gap-2 text-[12.5px]">
              <span
                className={`inline-flex h-4 w-4 items-center justify-center rounded-full shrink-0 ${
                  done ? 'bg-teal-500 text-white' : active ? 'border-2 border-teal-500' : 'border border-slate-300'
                }`}
                aria-hidden
              >
                {done && <CheckIcon s={10} />}
                {active && <span className="h-1.5 w-1.5 rounded-full bg-teal-500 animate-pulse" />}
              </span>
              <span className={done ? 'text-slate-500' : active ? 'text-slate-900 font-medium' : 'text-slate-400'}>
                {label[step]}
              </span>
            </li>
          )
        })}
      </ol>
      <p className="mt-2.5 text-[11.5px] text-slate-400">{P.hint}</p>
    </div>
  )
}
