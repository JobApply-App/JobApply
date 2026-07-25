import { TOKENS } from '@/lib/tokens'

export function Logo({ size = 24 }: { size?: number }) {
  return (
    <div className="inline-flex items-center gap-2">
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
        <rect width="32" height="32" rx="8" fill={TOKENS.color.primary}/>
        <path d="M9 11h14M9 16h10" stroke="white" strokeWidth="2.2" strokeLinecap="round"/>
        <circle cx="22" cy="21" r="3.5" fill="white"/>
        <path d="m20.3 21 1.3 1.3 2.3-2.7" stroke={TOKENS.color.primary} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
      <span className="font-semibold text-[15px] tracking-tight text-slate-900">Job Apply</span>
    </div>
  )
}
