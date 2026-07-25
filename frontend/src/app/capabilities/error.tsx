'use client'

import { useEffect } from 'react'

export default function CapabilitiesError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('[capabilities] Page error:', error)
  }, [error])

  return (
    <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-8">
      <div
        className="w-full max-w-md rounded-2xl bg-white border border-red-100 px-8 py-10 text-center"
        style={{ boxShadow: '0 4px 24px rgba(239,68,68,0.08)' }}
      >
        <div className="text-[36px] mb-4" aria-hidden="true">⚠️</div>
        <h1 className="text-[18px] font-bold text-slate-800 mb-2">
          Capabilities failed to load
        </h1>
        <p className="text-[13px] text-slate-500 leading-relaxed mb-1">
          {error.message || 'An unexpected error occurred while rendering this page.'}
        </p>
        {error.digest && (
          <p className="text-[11px] font-mono text-slate-400 mt-1 mb-6">
            Error ID: {error.digest}
          </p>
        )}
        {!error.digest && <div className="mb-6" />}
        <button
          onClick={reset}
          className="inline-flex items-center justify-center h-10 px-6 rounded-xl text-[13px] font-semibold text-white transition active:scale-[0.97]"
          style={{ background: '#0D9488' }}
        >
          Try again
        </button>
        <p className="text-[11px] text-slate-400 mt-4">
          If this persists, check the browser console for the full stack trace.
        </p>
      </div>
    </div>
  )
}
