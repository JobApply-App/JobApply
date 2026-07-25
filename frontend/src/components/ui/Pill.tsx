import { ReactNode } from 'react'
import type { Tone } from '@/lib/tokens'

const toneStyles: Record<Tone, string> = {
  success: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/60',
  warn:    'bg-amber-50 text-amber-700 ring-1 ring-amber-200/60',
  danger:  'bg-rose-50 text-rose-700 ring-1 ring-rose-200/60',
  muted:   'bg-slate-100 text-slate-500',
  primary: 'bg-teal-50 text-teal-700 ring-1 ring-teal-200/60',
}

interface PillProps {
  tone?: Tone
  children: ReactNode
}

export function Pill({ tone = 'muted', children }: PillProps) {
  return (
    <span className={`inline-flex items-center gap-1 h-5 px-2 rounded-full text-[11px] font-medium ${toneStyles[tone]}`}>
      {children}
    </span>
  )
}
