'use client'

import { useState, useEffect, useCallback } from 'react'
import { fetchApplicationsList, deleteApplication } from '@/lib/api'
import type { AppListItem } from '@/lib/api'
import { ApplicationsKanban } from './ApplicationsKanban'
import { TOKENS } from '@/lib/tokens'

// ── View toggle ───────────────────────────────────────────────────────────────

type View = 'list' | 'board'

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="flex items-center gap-1 p-1 bg-slate-100 rounded-lg">
      {(['list', 'board'] as View[]).map(v => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={`flex items-center gap-1.5 h-7 px-3 rounded-md text-[12px] font-medium transition-all duration-150 ${
            view === v
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          {v === 'list' ? <ListIcon /> : <BoardIcon />}
          {v === 'list' ? 'List' : 'Board'}
        </button>
      ))}
    </div>
  )
}

function ListIcon() {
  return (
    <svg width={13} height={13} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="8" y1="6"  x2="21" y2="6"  />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <circle cx="3" cy="6"  r="1" />
      <circle cx="3" cy="12" r="1" />
      <circle cx="3" cy="18" r="1" />
    </svg>
  )
}

function BoardIcon() {
  return (
    <svg width={13} height={13} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3"  y="3" width="7" height="18" rx="1" />
      <rect x="14" y="3" width="7" height="11" rx="1" />
      <rect x="14" y="18" width="7" height="3" rx="1" />
    </svg>
  )
}

// ── Stage badge ───────────────────────────────────────────────────────────────

const STAGE_COLORS: Record<string, string> = {
  submitted:    'bg-teal-100 text-teal-700',
  'phone screen': 'bg-sky-100 text-sky-700',
  technical:    'bg-violet-100 text-violet-700',
  interview:    'bg-amber-100 text-amber-700',
  offer:        'bg-emerald-100 text-emerald-700',
  rejected:     'bg-rose-100 text-rose-600',
}

function StageBadge({ stage }: { stage: string }) {
  const cls = STAGE_COLORS[stage.toLowerCase()] ?? 'bg-slate-100 text-slate-600'
  return (
    <span className={`text-[10.5px] font-semibold px-2 py-0.5 rounded-full ${cls}`}>
      {stage.charAt(0).toUpperCase() + stage.slice(1)}
    </span>
  )
}

// ── List view ─────────────────────────────────────────────────────────────────

function RowDeleteButton({ title, onConfirm, deleting }: { title: string; onConfirm: () => void; deleting: boolean }) {
  return (
    <button
      onClick={e => {
        e.stopPropagation()
        if (window.confirm(`Delete the application for "${title}"? This cannot be undone.`)) {
          onConfirm()
        }
      }}
      disabled={deleting}
      title="Delete application"
      className="shrink-0 h-7 px-2.5 rounded-lg text-[11px] font-medium border border-transparent text-rose-500 hover:bg-rose-50 hover:border-rose-100 transition disabled:opacity-50"
    >
      {deleting ? '…' : 'Delete'}
    </button>
  )
}

function ApplicationListView({ items, loading, error, onDelete, deletingId }: {
  items:      AppListItem[]
  loading:    boolean
  error:      string | null
  onDelete:   (id: string) => void
  deletingId: string | null
}) {
  if (loading) {
    return (
      <div className="space-y-2 mt-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-16 rounded-2xl bg-slate-100 animate-pulse" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-40 text-sm" style={{ color: TOKENS.color.danger }}>
        Failed to load applications. {error}
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-slate-400">
        <svg width={36} height={36} viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
          className="mb-3 opacity-40">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
        <p className="text-[13px] font-medium text-slate-500">No applications yet</p>
        <p className="text-[12px] text-slate-400 mt-1">
          Tailor a CV and click "Mark as Applied" to track it here
        </p>
      </div>
    )
  }

  return (
    <div className="mt-4 space-y-2">
      {items.map(item => (
        <div
          key={item.application_id}
          className="flex items-center gap-4 bg-white rounded-2xl border border-slate-100 px-4 py-3 hover:border-slate-200 hover:shadow-sm transition-all duration-150"
        >
          {/* Company + title */}
          <div className="flex-1 min-w-0">
            <p className="text-[13px] font-semibold text-slate-900 truncate">{item.title}</p>
            <p className="text-[12px] text-slate-500 truncate mt-0.5">{item.company}</p>
          </div>

          {/* Stage badge */}
          <StageBadge stage={item.status} />

          {/* Score */}
          {item.score > 0 && (
            <span className="text-[11px] font-semibold text-slate-400 shrink-0">
              {Math.round(item.score)}%
            </span>
          )}

          {/* Last update */}
          <span className="text-[11px] text-slate-400 shrink-0 hidden sm:block">
            {item.last_update}
          </span>

          <RowDeleteButton
            title={item.title}
            onConfirm={() => onDelete(item.application_id)}
            deleting={deletingId === item.application_id}
          />
        </div>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ApplicationsTab() {
  const [view,       setView]       = useState<View>('board')
  const [items,      setItems]      = useState<AppListItem[]>([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const loadList = useCallback(async () => {
    setLoading(true)
    try {
      // Uses the auth-aware api helper — same token as the Board view.
      const data = await fetchApplicationsList()
      setItems(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  // Runs once on mount (needed even in Board view, since the header's
  // total/active counts read from `items` regardless of which view is shown).
  useEffect(() => { loadList() }, [loadList])

  // Re-fetch every time the user switches to List view. Without this, a
  // transient failure in the mount-time fetch above (e.g. the backend still
  // warming up right when the tab first loads) leaves `error` permanently
  // set — and since only ApplicationListView renders that error, the user
  // only ever sees the stale failure the moment they click "List", by which
  // point the backend may be perfectly healthy again. This gives List view
  // its own fresh attempt instead of surfacing a possibly-outdated error.
  useEffect(() => {
    if (view === 'list') loadList()
  }, [view, loadList])

  useEffect(() => {
    if (!deleteError) return
    const t = setTimeout(() => setDeleteError(null), 4000)
    return () => clearTimeout(t)
  }, [deleteError])

  const handleDeleteItem = useCallback(async (id: string) => {
    setDeletingId(id)
    setDeleteError(null)
    const previous = items
    setItems(prev => prev.filter(i => i.application_id !== id))   // optimistic
    try {
      await deleteApplication(id)
    } catch (e) {
      setItems(previous)   // rollback
      setDeleteError(e instanceof Error ? e.message : String(e))
    } finally {
      setDeletingId(null)
    }
  }, [items])

  const totalApps  = items.length
  const activeApps = items.filter(i =>
    ['submitted', 'phone screen', 'technical', 'interview'].includes(i.status.toLowerCase())
  ).length

  return (
    <section className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[15px] font-semibold text-slate-900">Applications</h2>
          <p className="text-[12px] text-slate-500 mt-0.5">
            {loading ? '—' : `${totalApps} total · ${activeApps} active in pipeline`}
          </p>
        </div>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {deleteError && (
        <div className="text-[12px] px-3 py-2 rounded-lg" style={{ color: TOKENS.color.danger, background: '#FEF2F2' }}>
          Delete failed: {deleteError}
        </div>
      )}

      {/* Content */}
      {view === 'board' ? (
        <ApplicationsKanban onRefresh={loadList} />
      ) : (
        <ApplicationListView
          items={items}
          loading={loading}
          error={error}
          onDelete={handleDeleteItem}
          deletingId={deletingId}
        />
      )}
    </section>
  )
}
