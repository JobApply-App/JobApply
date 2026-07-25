import type { Application } from '@/lib/data'
import { StatusDot } from './ui/StatusDot'
import type { Tone } from '@/lib/tokens'

type Stage = Application['stage']

const STAGE_META: Record<Stage, { label: string; tone: Tone }> = {
  submitted: { label: 'Submitted', tone: 'muted'   },
  viewed:    { label: 'Viewed',    tone: 'primary'  },
  screening: { label: 'Screening', tone: 'primary'  },
  interview: { label: 'Interview', tone: 'success'  },
  offer:     { label: 'Offer',     tone: 'success'  },
  rejected:  { label: 'Rejected',  tone: 'muted'    },
}

function TrackerRow({ app }: { app: Application }) {
  const s = STAGE_META[app.stage]
  return (
    <li className="flex items-center gap-4 py-3">
      <StatusDot tone={s.tone} size={7} pulse={app.stage === 'interview' || app.stage === 'offer'} />
      <div className="flex-1 min-w-0">
        <div className="text-[13.5px] text-slate-900 truncate font-medium">{app.title}</div>
        <div className="text-[12px] text-slate-500">{app.company}</div>
      </div>
      <div className="text-right shrink-0">
        <div className={`text-[12.5px] font-medium ${app.stage === 'rejected' ? 'text-slate-400' : 'text-slate-900'}`}>
          {s.label}
        </div>
        <div className="text-[11px] text-slate-400">{app.when}</div>
      </div>
    </li>
  )
}

interface TrackerProps {
  apps: Application[]
  embedded?: boolean
}

export function Tracker({ apps, embedded }: TrackerProps) {
  const active = apps.filter(a => a.stage !== 'rejected').length
  return (
    <section>
      {!embedded && (
        <header className="mb-3">
          <h2 className="text-[20px] font-semibold text-slate-900 tracking-tight">Applications</h2>
          <p className="text-[13px] text-slate-500 mt-0.5">{active} active · synced with ATS</p>
        </header>
      )}
      <ul
        className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white px-4"
        style={{ boxShadow: '0 1px 2px rgba(15,23,42,0.03)' }}
      >
        {apps.map(a => <TrackerRow key={a.id} app={a} />)}
      </ul>
    </section>
  )
}
