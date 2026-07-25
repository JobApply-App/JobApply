'use client'
import { useCallback, useState } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { OnboardingHeader } from '@/components/OnboardingHeader'
import { useAuth } from '@/contexts/AuthContext'
import { useOnboarding } from '@/contexts/OnboardingContext'
import { resolveDisplayName } from '@/lib/nameUtils'
import { fetchRolePreferences, uploadCvFiles } from '@/lib/api'
import { armArielWelcome } from '@/lib/onboardingFlags'
import { TOKENS } from '@/lib/tokens'

// ── Upload states ──────────────────────────────────────────────────────────

type UploadState = 'idle' | 'uploading' | 'done' | 'error'

// ── Drag-and-drop zone ─────────────────────────────────────────────────────

function UploadZone({
  onFiles,
  disabled,
}: {
  onFiles: (files: File[]) => void
  disabled: boolean
}) {
  const [dragOver, setDragOver] = useState(false)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      if (disabled) return
      const files = Array.from(e.dataTransfer.files).filter(f =>
        f.name.match(/\.(pdf|docx)$/i)
      )
      if (files.length) onFiles(files)
    },
    [disabled, onFiles]
  )

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length) onFiles(files)
    e.target.value = ''
  }

  return (
    <label
      onDragOver={e => { e.preventDefault(); if (!disabled) setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={`relative flex flex-col items-center justify-center gap-4 w-full max-w-lg mx-auto rounded-2xl border-2 border-dashed transition-all cursor-pointer select-none py-14 px-8 ${
        disabled ? 'cursor-not-allowed opacity-50' :
        dragOver  ? 'border-teal-400 bg-teal-50/60' :
                    'border-slate-200 bg-white hover:border-teal-300 hover:bg-teal-50/30'
      }`}
      style={{ boxShadow: '0 2px 12px rgba(0,0,0,0.04)' }}
    >
      <input
        type="file"
        accept=".pdf,.docx"
        multiple
        className="sr-only"
        disabled={disabled}
        onChange={handleChange}
      />

      {/* Icon */}
      <div
        className="flex items-center justify-center w-16 h-16 rounded-full"
        style={{ background: 'oklch(0.94 0.04 175)' }}
      >
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
          stroke={TOKENS.color.primary} strokeWidth="1.8"
          strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      </div>

      <div className="text-center space-y-1">
        <p className="text-[15px] font-semibold text-slate-800">
          {dragOver ? 'Drop your resume here' : 'Upload your resume'}
        </p>
        <p className="text-[13px] text-slate-400">
          Drag & drop or click to select — PDF or DOCX
        </p>
      </div>
    </label>
  )
}

// ── Progress / result states ───────────────────────────────────────────────

function UploadingState() {
  return (
    <div className="flex flex-col items-center gap-5 py-10">
      <div
        className="w-14 h-14 rounded-full border-4 border-t-transparent animate-spin"
        style={{ borderColor: `${TOKENS.color.primary} transparent transparent transparent` }}
      />
      <div className="text-center space-y-1">
        <p className="text-[15px] font-semibold text-slate-800">
          Uploading and analyzing…
        </p>
        <p className="text-[13px] text-slate-400">
          Our AI is analyzing your experience, skills, and education…
        </p>
      </div>
    </div>
  )
}

function DoneState({ skillCount, expCount }: { skillCount: number; expCount: number }) {
  return (
    <div className="flex flex-col items-center gap-5 py-10">
      <div
        className="flex items-center justify-center w-14 h-14 rounded-full"
        style={{ background: 'oklch(0.93 0.07 150)' }}
      >
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none"
          stroke="oklch(0.35 0.14 155)" strokeWidth="2.2"
          strokeLinecap="round" strokeLinejoin="round"
        >
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </div>
      <div className="text-center space-y-1">
        <p className="text-[15px] font-semibold text-slate-800">Profile imported!</p>
        <p className="text-[13px] text-slate-400">
          Found {expCount} role{expCount !== 1 ? 's' : ''} and {skillCount} skill{skillCount !== 1 ? 's' : ''}.
          Taking you to your dashboard…
        </p>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

function ProfileBuilderContent() {
  const router = useRouter()
  const { user, updateUserMeta } = useAuth()
  const { set: setOnboarding }   = useOnboarding()
  const [state,      setState]      = useState<UploadState>('idle')
  const [errorMsg,   setErrorMsg]   = useState('')
  const [skillCount, setSkillCount] = useState(0)
  const [expCount,   setExpCount]   = useState(0)

  const handleFiles = useCallback(async (files: File[]) => {
    setState('uploading')
    setErrorMsg('')
    try {
      const result = await uploadCvFiles(files)
      const skills = result.cv_claims?.skills?.length ?? 0
      const exps   = result.cv_claims?.experiences?.length ?? 0
      setSkillCount(skills)
      setExpCount(exps)
      setState('done')

      // ── Onboarding completion handoff ────────────────────────────────────
      // 1. Seed the greeting data Ariel personalises her welcome with —
      //    including the saved role/seniority preferences (live fetch).
      // 2. Mark the profile complete (unlocks Ariel globally) BEFORE routing
      //    so the dashboard renders in the completed state with no flash.
      // 3. Arm the one-shot auto-open flag, then SOFT-navigate with
      //    router.push — no window.location.assign (the hard reload caused
      //    ChunkLoadError and wiped local React state).
      const meta  = user?.user_metadata as Record<string, unknown> | null
      const prefs = await fetchRolePreferences().catch(() => ({ roles: [] }))
      setOnboarding({
        fullName:    resolveDisplayName(user?.email, meta),
        careerStage: typeof meta?.career_stage === 'string' ? meta.career_stage : '',
        roles:       prefs.roles,
      })
      try { await updateUserMeta({ profile_completed: true }) } catch { /* backfilled by sync-user */ }
      armArielWelcome()
      setTimeout(() => router.push('/?tab=overview'), 1400)
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Upload failed. Please try again.')
      setState('error')
    }
  }, [user, updateUserMeta, setOnboarding, router])

  return (
    <div className="flex flex-col items-center justify-center flex-1 px-4 py-12">
      {/* Back to the onboarding steps */}
      <div className="w-full max-w-lg mx-auto mb-4">
        <button
          onClick={() => router.push('/onboarding')}
          disabled={state === 'uploading'}
          className="text-[13px] text-slate-400 hover:text-slate-700 flex items-center gap-1 transition disabled:opacity-40"
        >
          ← Back
        </button>
      </div>

      {/* Header copy */}
      <div className="text-center mb-10 space-y-2 max-w-md">
        <h1 className="text-[28px] font-bold text-slate-900 tracking-tight">
          Import your resume
        </h1>
        <p className="text-[14px] text-slate-500 leading-relaxed">
          Upload your CV and we&apos;ll extract your work history, skills, and
          education to power accurate Match Scores.
        </p>
      </div>

      {/* State machine */}
      {state === 'uploading' ? (
        <UploadingState />
      ) : state === 'done' ? (
        <DoneState skillCount={skillCount} expCount={expCount} />
      ) : (
        <UploadZone onFiles={handleFiles} disabled={false} />
      )}

      {/* Error */}
      {state === 'error' && (
        <div className="mt-6 w-full max-w-lg rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
          <strong className="font-semibold">Upload failed:</strong> {errorMsg}
          <button
            onClick={() => setState('idle')}
            className="ml-3 underline hover:no-underline"
          >
            Try again
          </button>
        </div>
      )}

      {/* Skip link */}
      {state === 'idle' && (
        <button
          onClick={() => router.push('/discover')}
          className="mt-8 text-[13px] text-slate-400 hover:text-slate-700 underline transition-colors"
        >
          Skip for now
        </button>
      )}
    </div>
  )
}

export default function ProfileBuilderPage() {
  return (
    <AuthGuard>
      <div className="flex flex-col h-screen bg-[#FBFBFA] overflow-hidden">
        <OnboardingHeader />
        <main className="flex flex-1 overflow-hidden min-h-0">
          <div className="flex-1 min-w-0 overflow-y-auto">
            <ProfileBuilderContent />
          </div>
        </main>
      </div>
    </AuthGuard>
  )
}
