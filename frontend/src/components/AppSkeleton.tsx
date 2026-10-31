'use client'

import { Logo } from './ui/Logo'
import { Skeleton } from './ui/Skeleton'

// What a signed-in user sees for the moment the session is being read: the
// app's own frame, light, with its sections still filling in. It replaced a
// dark full-screen spinner ("Securing your workspace and activating
// agents… Please wait."), which made every login feel like a wait.

/** True when this browser holds a Supabase session, so the page about to
 *  load is the app rather than the landing page. Read before auth resolves. */
export function hasStoredSession(): boolean {
  try {
    return Object.keys(window.localStorage).some(k => k.startsWith('sb-') && k.endsWith('-auth-token'))
  } catch {
    return false
  }
}

export function AppSkeleton() {
  return (
    <div className="min-h-screen bg-ja-bg" aria-busy="true">
      <div className="w-full ja-glass border-b border-slate-100/70 h-14 md:h-[60px] px-4 sm:px-6 lg:px-12 flex items-center">
        <Logo />
      </div>
      <main className="max-w-content mx-auto w-full px-4 sm:px-6 py-6 sm:py-8 grid gap-6 animate-ja-fade">
        <Skeleton className="h-8 w-56" />
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-28 rounded-2xl" />
          <Skeleton className="h-28 rounded-2xl" />
          <Skeleton className="h-28 rounded-2xl" />
        </div>
        <Skeleton className="h-64 rounded-2xl" />
      </main>
    </div>
  )
}
