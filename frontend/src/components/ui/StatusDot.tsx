import { TOKENS, type Tone } from '@/lib/tokens'

const toneColors: Record<Tone, string> = {
  success: TOKENS.color.success,
  warn:    TOKENS.color.warn,
  danger:  TOKENS.color.danger,
  muted:   '#CBD5E1',
  primary: TOKENS.color.primary,
}

interface StatusDotProps {
  tone?: Tone
  pulse?: boolean
  size?: number
}

export function StatusDot({ tone = 'success', pulse = false, size = 8 }: StatusDotProps) {
  const color = toneColors[tone]
  return (
    <span className="relative inline-flex" style={{ width: size, height: size }}>
      {pulse && (
        <span
          className="absolute inline-flex h-full w-full rounded-full opacity-60"
          style={{ background: color, animation: 'ja-ping 1.8s cubic-bezier(0,0,.2,1) infinite' }}
        />
      )}
      <span
        className="relative inline-flex rounded-full"
        style={{ width: size, height: size, background: color }}
      />
    </span>
  )
}
