'use client'

import { useCallback, useRef, useState } from 'react'
import { TOKENS } from '@/lib/tokens'
import { uploadCvFiles, type CvClaimsResult } from '@/lib/api'

// ── Icons ─────────────────────────────────────────────────────────────────────

function UploadCloudIcon({ s = 20 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 16 12 12 8 16" />
      <line x1="12" y1="12" x2="12" y2="21" />
      <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3" />
    </svg>
  )
}

function FileIcon({ s = 14 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function SpinnerIcon({ s = 16 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 0.8s linear infinite', flexShrink: 0 }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function XIcon({ s = 12 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const ALLOWED_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]

function isAllowed(file: File): boolean {
  if (ALLOWED_TYPES.includes(file.type)) return true
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  return ext === 'pdf' || ext === 'docx'
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ClaimsSummary({ claims }: { claims: CvClaimsResult }) {
  const hasContent = claims.skills.length > 0 ||
                     claims.experiences.length > 0 ||
                     claims.education.length > 0

  if (!hasContent) return null

  return (
    <div
      className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 mt-4 space-y-3"
      style={{ fontSize: 12.5 }}
    >
      <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">
        CV Claims Extracted — Jonathan will probe these
      </p>

      {claims.summary && (
        <p className="text-slate-600 leading-relaxed">{claims.summary}</p>
      )}

      {claims.skills.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold text-slate-500 mb-1.5">Skills claimed</p>
          <div className="flex flex-wrap gap-1.5">
            {claims.skills.slice(0, 20).map(sk => (
              <span
                key={sk}
                className="h-6 px-2.5 rounded-full bg-white border border-emerald-200 text-slate-700 text-[11px] font-medium"
              >
                {sk}
              </span>
            ))}
            {claims.skills.length > 20 && (
              <span className="h-6 px-2.5 rounded-full bg-slate-100 text-slate-400 text-[11px] font-medium">
                +{claims.skills.length - 20} more
              </span>
            )}
          </div>
        </div>
      )}

      {claims.experiences.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold text-slate-500 mb-1.5">Roles claimed</p>
          <div className="space-y-1">
            {claims.experiences.slice(0, 5).map((e, i) => (
              <div key={i} className="flex items-baseline gap-1.5">
                <span className="font-semibold text-slate-700">{e.role}</span>
                <span className="text-slate-400">at</span>
                <span className="text-slate-700">{e.company}</span>
                {(e.start || e.end) && (
                  <span className="text-slate-400 text-[11px]">
                    ({[e.start, e.end].filter(Boolean).join('–')})
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {claims.education.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold text-slate-500 mb-1.5">Education claimed</p>
          <div className="space-y-1">
            {claims.education.map((e, i) => (
              <div key={i} className="text-slate-700">
                {e.degree}
                {e.institution && <span className="text-slate-400"> — {e.institution}</span>}
                {e.years && <span className="text-slate-400 text-[11px]"> ({e.years})</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface CvUploadPanelProps {
  /** Called when aggregation completes so the parent can react (e.g. refresh) */
  onUploaded?: (claims: CvClaimsResult) => void
}

export function CvUploadPanel({ onUploaded }: CvUploadPanelProps) {
  const [files,      setFiles]      = useState<File[]>([])
  const [uploading,  setUploading]  = useState(false)
  const [result,     setResult]     = useState<CvClaimsResult | null>(null)
  const [errors,     setErrors]     = useState<string[]>([])
  const [dragOver,   setDragOver]   = useState(false)

  const inputRef    = useRef<HTMLInputElement>(null)
  const dragCounter = useRef(0)

  // ── File management ──────────────────────────────────────────────────────────

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const valid = Array.from(incoming).filter(isAllowed)
    if (!valid.length) return
    setFiles(prev => {
      const existing = new Set(prev.map(f => f.name))
      const fresh    = valid.filter(f => !existing.has(f.name))
      return [...prev, ...fresh].slice(0, 10)
    })
    // Reset prior result when new files are added
    setResult(null)
    setErrors([])
  }, [])

  const removeFile = useCallback((name: string) => {
    setFiles(prev => prev.filter(f => f.name !== name))
    setResult(null)
  }, [])

  // ── Drag & drop ──────────────────────────────────────────────────────────────

  const onDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current++
    if (dragCounter.current === 1) setDragOver(true)
  }, [])

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current--
    if (dragCounter.current === 0) setDragOver(false)
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current = 0
    setDragOver(false)
    addFiles(e.dataTransfer.files)
  }, [addFiles])

  // ── Upload ───────────────────────────────────────────────────────────────────

  const handleUpload = useCallback(async () => {
    if (!files.length || uploading) return
    setUploading(true)
    setErrors([])
    try {
      const res = await uploadCvFiles(files)
      setResult(res.cv_claims)
      if (res.errors?.length) setErrors(res.errors)
      onUploaded?.(res.cv_claims)
    } catch (err: unknown) {
      setErrors([(err as Error).message ?? 'Upload failed. Please try again.'])
    } finally {
      setUploading(false)
    }
  }, [files, uploading, onUploaded])

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div
      className="bg-white rounded-xl border border-slate-100 shadow-sm flex flex-col gap-0 overflow-hidden"
    >
      {/* Header */}
      <div
        className="px-5 py-4 border-b border-slate-100"
        style={{ background: 'oklch(0.97 0.01 290)' }}
      >
        <p style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '1.3px',
          textTransform: 'uppercase', color: TOKENS.color.primary,
          marginBottom: 2,
        }}>
          CV Context for Jonathan
        </p>
        <p style={{ fontSize: 12, color: TOKENS.color.muted, lineHeight: 1.5 }}>
          Upload your CVs so Jonathan can probe your claimed skills and experiences in the interview.
        </p>
      </div>

      <div className="px-5 py-4 flex flex-col gap-3">
        {/* Drop zone */}
        <div
          onDragEnter={onDragEnter}
          onDragLeave={onDragLeave}
          onDragOver={e => e.preventDefault()}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`relative border-2 border-dashed rounded-xl px-4 py-5 flex flex-col items-center gap-2 cursor-pointer transition
            ${dragOver
              ? 'border-violet-400 bg-violet-50'
              : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
            }`}
        >
          <UploadCloudIcon s={26} />
          <p className="text-[12.5px] font-medium text-slate-700 text-center">
            Drop PDF or DOCX files here
          </p>
          <p className="text-[11px] text-slate-400 text-center">
            or click to select — up to 10 files, 10 MB each
          </p>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.docx"
            multiple
            className="hidden"
            onChange={e => { if (e.target.files) addFiles(e.target.files) }}
          />
        </div>

        {/* File list */}
        {files.length > 0 && (
          <div className="space-y-1.5">
            {files.map(f => (
              <div
                key={f.name}
                className="flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2"
              >
                <FileIcon s={13} />
                <span
                  className="flex-1 min-w-0 text-[12px] text-slate-700 font-medium truncate"
                  title={f.name}
                >
                  {f.name}
                </span>
                <span className="text-[10.5px] text-slate-400 shrink-0">
                  {(f.size / 1024).toFixed(0)} KB
                </span>
                <button
                  onClick={e => { e.stopPropagation(); removeFile(f.name) }}
                  className="text-slate-300 hover:text-rose-400 transition flex-shrink-0"
                  title="Remove"
                >
                  <XIcon s={11} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Upload button */}
        {files.length > 0 && !result && (
          <button
            onClick={handleUpload}
            disabled={uploading}
            className="h-9 rounded-xl text-[13px] font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-60 transition"
            style={{ background: 'oklch(0.52 0.18 290)' }}
          >
            {uploading ? (
              <><SpinnerIcon s={15} /> Extracting &amp; aggregating…</>
            ) : (
              `✦ Process ${files.length} CV${files.length > 1 ? 's' : ''}`
            )}
          </button>
        )}

        {/* Errors */}
        {errors.length > 0 && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2.5 space-y-1">
            {errors.map((e, i) => (
              <p key={i} className="text-[11.5px] text-rose-700">{e}</p>
            ))}
          </div>
        )}

        {/* Success — extracted claims summary */}
        {result && (
          <>
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5">
              <span className="text-emerald-600 text-[13px]">✓</span>
              <p className="text-[12.5px] font-semibold text-emerald-800 flex-1">
                {files.length} CV{files.length > 1 ? 's' : ''} processed —
                Jonathan will probe these claims in your next interview.
              </p>
              <button
                onClick={() => { setFiles([]); setResult(null); setErrors([]) }}
                className="text-emerald-600 hover:text-emerald-900 text-[11px] shrink-0 underline"
              >
                Upload more
              </button>
            </div>

            <ClaimsSummary claims={result} />
          </>
        )}
      </div>
    </div>
  )
}
