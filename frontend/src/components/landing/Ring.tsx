import { getScoreBand } from '@/lib/scoreBand'

export function Ring({ value, size = 72 }: { value: number; size?: number }) {
  const band = getScoreBand(value)
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90" aria-hidden="true">
        <circle cx="18" cy="18" r="15.9" fill="none" stroke={band.hexBg} strokeWidth="3.2" pathLength={100} />
        <circle cx="18" cy="18" r="15.9" fill="none" stroke={band.hexFg} strokeWidth="3.2" strokeLinecap="round"
          pathLength={100} strokeDasharray={`${value} 100`} />
      </svg>
      <span className="absolute inset-0 grid place-items-center font-bold tabular-nums tracking-tight"
        style={{ color: band.key === 'moderate' ? '#B45309' : band.hexFg, fontSize: size * 0.21 }}>
        {value.toFixed(1)}
      </span>
    </div>
  )
}
