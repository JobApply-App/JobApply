'use client'
import { TOKENS } from '@/lib/tokens'

interface ToggleProps {
  on: boolean
  onChange: (v: boolean) => void
  size?: 'sm' | 'md'
}

export function Toggle({ on, onChange, size = 'md' }: ToggleProps) {
  const w = size === 'sm' ? 32 : 40
  const h = size === 'sm' ? 18 : 22
  const d = h - 4
  return (
    <button
      onClick={() => onChange(!on)}
      className="inline-flex items-center rounded-full transition-colors"
      style={{ width: w, height: h, background: on ? TOKENS.color.primary : '#E2E8F0', padding: 2 }}
    >
      <span
        className="rounded-full bg-white shadow transition-transform"
        style={{ width: d, height: d, transform: `translateX(${on ? w - d - 4 : 0}px)` }}
      />
    </button>
  )
}
