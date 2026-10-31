'use client'

import { useI18n } from '@/contexts/I18nContext'

/** "Step n of 3" over signup (1), about you (2) and the CV upload (3). */
export function SignupSteps({ current }: { current: 1 | 2 | 3 }) {
  const S = useI18n().t.signup.steps
  const total = S.names.length
  return (
    <div className="mb-6">
      <p className="text-[13px] text-slate-500 mb-2">
        {S.label.replace('{n}', String(current)).replace('{total}', String(total)).replace('{name}', S.names[current - 1])}
      </p>
      <ol className="flex gap-1.5" aria-hidden="true">
        {S.names.map((_, i) => (
          <li key={i} className={`h-1 flex-1 rounded-full ${i < current ? 'bg-[#0F766E]' : 'bg-slate-200'}`} />
        ))}
      </ol>
    </div>
  )
}
