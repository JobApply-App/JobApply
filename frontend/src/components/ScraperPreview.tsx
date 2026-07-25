'use client'

import { useCallback, useState } from 'react'

// ── ATS Parser Preview (JOB-66) ───────────────────────────────────────────────
//
// Admin/user tool over POST /api/v1/scraper/preview: paste a job URL (or raw
// HTML when the target blocks server-side fetching) and see exactly what the
// Core Scraping Architecture extracts — title, company, and the raw text an
// ATS parser would read. Useful for debugging extraction quality per source
// before a dedicated adapter exists.

/** Mirrors models/job.py RawJobPosting returned by the preview endpoint. */
interface ScraperPreviewResult {
  id:         string
  title:      string
  company:    string
  source_url: string
  raw_text:   string
  scraped_at: string
}

function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'spin 0.8s linear infinite' }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.25" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10.5px] font-bold tracking-widest uppercase text-slate-400 mb-1.5">
      {children}
    </p>
  )
}

function fmtScrapedAt(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export function ScraperPreview() {
  const [url,      setUrl]      = useState('')
  const [rawHtml,  setRawHtml]  = useState('')
  const [showHtml, setShowHtml] = useState(false)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)
  const [result,   setResult]   = useState<ScraperPreviewResult | null>(null)
  const [copied,   setCopied]   = useState(false)

  const runPreview = useCallback(async () => {
    const trimmedUrl = url.trim()
    if (!trimmedUrl || loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch('/api/v1/scraper/preview', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: trimmedUrl,
          ...(showHtml && rawHtml.trim() ? { html: rawHtml } : {}),
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        const detail = (body as { detail?: unknown }).detail
        throw new Error(
          typeof detail === 'string'
            ? detail
            : res.status === 422
              ? 'Invalid URL — include the protocol (https://…).'
              : `Preview failed (HTTP ${res.status}).`,
        )
      }
      setResult(await res.json() as ScraperPreviewResult)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [url, rawHtml, showHtml, loading])

  const copyRawText = useCallback(() => {
    if (!result) return
    navigator.clipboard.writeText(result.raw_text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => {})
  }, [result])

  return (
    <section className="max-w-3xl space-y-8">

      {/* ── Heading ─────────────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-[22px] font-semibold text-slate-900 tracking-tight">
          ATS Parser Preview
        </h1>
        <p className="text-[13px] text-slate-500 mt-1">
          See exactly what the scraping engine extracts from a job posting —
          the same raw text an ATS parser reads.
        </p>
      </div>

      {/* ── Input form ──────────────────────────────────────────────────────── */}
      <form onSubmit={e => { e.preventDefault(); runPreview() }} className="space-y-2.5">
        <div className="flex gap-2">
          <input
            type="url"
            placeholder="https://boards.greenhouse.io/company/jobs/123…"
            value={url}
            onChange={e => setUrl(e.target.value)}
            disabled={loading}
            className="flex-1 h-9 px-3 rounded-lg border border-slate-200 bg-white text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-400 transition disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={loading || !url.trim()}
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg text-[13px] font-medium text-white bg-ja-primary hover:bg-ja-primaryHover transition active:scale-[0.97] disabled:opacity-50 disabled:pointer-events-none"
          >
            {loading ? <><Spinner size={13} /> Scraping…</> : 'Preview'}
          </button>
        </div>

        {/* Optional raw-HTML bypass — for sources that block server fetching */}
        <button
          type="button"
          onClick={() => setShowHtml(v => !v)}
          className="flex items-center gap-1.5 text-[12px] font-medium text-slate-500 hover:text-slate-800 transition"
        >
          <span className="text-[10px]">{showHtml ? '▼' : '▶'}</span>
          Paste raw HTML instead of fetching
        </button>
        {showHtml && (
          <textarea
            value={rawHtml}
            onChange={e => setRawHtml(e.target.value)}
            placeholder="<html>… paste the page source here when the site blocks server-side fetching"
            rows={5}
            disabled={loading}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-[11.5px] text-slate-800 placeholder:text-slate-400 placeholder:font-sans focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-400 transition disabled:opacity-50 resize-y"
          />
        )}
      </form>

      {/* ── Error banner ────────────────────────────────────────────────────── */}
      {error && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3">
          <p className="text-[13px] text-rose-700">
            <span className="font-medium">Could not generate preview</span>
            <span className="text-rose-500">: {error}</span>
          </p>
        </div>
      )}

      {/* ── Loading skeleton ────────────────────────────────────────────────── */}
      {loading && (
        <div className="bg-white rounded-2xl border border-slate-100 shadow-elevation-1 p-6 space-y-3">
          <div className="h-5 w-64 rounded-lg bg-slate-100 animate-pulse" />
          <div className="h-3.5 w-40 rounded bg-slate-100 animate-pulse" />
          <div className="space-y-2 pt-3">
            {[100, 90, 95, 70].map((w, i) => (
              <div key={i} className="h-3 rounded bg-slate-100 animate-pulse" style={{ width: `${w}%` }} />
            ))}
          </div>
        </div>
      )}

      {/* ── Result ──────────────────────────────────────────────────────────── */}
      {result && !loading && (
        <div className="bg-white rounded-2xl border border-slate-100 shadow-elevation-1 p-6 space-y-5">

          {/* Extracted metadata */}
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <SectionLabel>Extracted Title</SectionLabel>
              <h2 dir="auto" className="text-[15px] font-bold text-slate-900 tracking-tight [unicode-bidi:plaintext] text-start">
                {result.title}
              </h2>
              <p className="text-[12.5px] text-slate-500 mt-1" dir="auto">
                {result.company}
                <span className="text-slate-300"> · </span>
                <span className="tabular-nums">{fmtScrapedAt(result.scraped_at)}</span>
              </p>
            </div>
            <a
              href={result.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[11.5px] font-semibold border border-teal-200 bg-teal-50 text-teal-700 hover:bg-teal-100 transition"
            >
              Source ↗
            </a>
          </div>

          {/* Raw parsed text */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <SectionLabel>Raw Parsed Text</SectionLabel>
              <div className="flex items-center gap-2.5 -mt-1">
                <span className="text-[11px] text-slate-400 tabular-nums">
                  {result.raw_text.length.toLocaleString()} chars
                </span>
                <button
                  onClick={copyRawText}
                  className={`h-6 px-2 rounded-lg text-[11px] font-medium border transition ${
                    copied
                      ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {copied ? 'Copied!' : 'Copy'}
                </button>
              </div>
            </div>
            <div
              dir="auto"
              className="max-h-[26rem] overflow-y-auto rounded-lg bg-slate-50 border border-slate-200 px-4 py-3 whitespace-pre-wrap text-[12px] leading-relaxed text-slate-700 [unicode-bidi:plaintext] text-start"
              style={{ boxShadow: 'inset 0 2px 4px rgba(15,23,42,0.04)' }}
            >
              {result.raw_text || (
                <span className="italic text-slate-400">No text extracted from this page.</span>
              )}
            </div>
            {result.raw_text.length > 0 && result.raw_text.length < 300 && (
              <p className="text-[11.5px] text-amber-600 mt-1.5">
                ⚠ Under 300 characters — this would fail the thin-JD gate and score as un-hydrated.
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
