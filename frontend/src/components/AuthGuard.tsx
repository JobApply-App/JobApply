'use client'

/**
 * AuthGuard — route-level authentication gate.
 *
 * Wraps a page (or layout subtree) and enforces authentication unconditionally:
 *   1. Shows the app's skeleton frame while Supabase resolves the session
 *      (the initial getSession() call takes ~50–150 ms on a warm connection).
 *   2. Redirects immediately to /login when loading completes with no user.
 *      Returns null so no protected content is ever rendered before the
 *      redirect navigation commits.
 *   3. Renders children only after a confirmed, validated session exists.
 *
 * Usage:
 *   export default function ProtectedPage() {
 *     return <AuthGuard><YourPageContent /></AuthGuard>
 *   }
 */

import { useEffect, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'

import { useAuth } from '@/contexts/AuthContext'
import { AppSkeleton } from './AppSkeleton'

interface AuthGuardProps {
  children: ReactNode
}

export default function AuthGuard({ children }: AuthGuardProps) {
  const { user, loading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (loading) return
    // No authenticated user → hard-navigate to login.
    // router.push (not replace) so the browser back-button works after login.
    if (!user) router.push('/login')
  }, [user, loading, router])

  // Session check in progress: the app's light frame, never protected content.
  if (loading) return <AppSkeleton />

  // Session resolved as null — redirect is in flight; render nothing to
  // guarantee zero flash of protected content while navigation commits.
  if (!user) return null

  return <>{children}</>
}
