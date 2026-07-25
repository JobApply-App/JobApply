'use client'
import { useCallback, useEffect, useState } from 'react'
import { fetchAgents }                from '@/lib/api'
import { useAuth }                    from '@/contexts/AuthContext'
import type { ApiAgentStatus }        from '@/lib/apiTypes'

// Static frontend: no automatic polling.
// Agent status is fetched ONCE when auth is ready and when the user clicks Refresh.

interface UseAgentStatusResult {
  agents:  ApiAgentStatus[]
  loading: boolean
  error:   string | null
  refetch: () => void
}

export function useAgentStatus(): UseAgentStatusResult {
  const { session, loading: authLoading } = useAuth()

  const [agents,  setAgents]  = useState<ApiAgentStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)

  // fetchAgents() goes through the authenticated get() wrapper, which awaits
  // ensureFreshToken() and attaches the current Bearer token itself. The old
  // implementation called setAuthToken(session.access_token) with the token
  // captured in React state — after a refresh or the post-onboarding
  // USER_UPDATED window that token could be stale, overwriting the fresh one
  // and producing 401s on /api/agents/. Never inject tokens manually here.
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchAgents()
      setAgents(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch agent status')
    } finally {
      setLoading(false)
    }
  }, [])

  // Fire once auth has resolved (and again if the session identity changes).
  // The previous mount-only effect raced the session: when it ran before the
  // token existed it bailed and never retried, leaving the widget stuck.
  useEffect(() => {
    if (authLoading || !session) return
    void load()
  }, [authLoading, session?.user?.id, load])   // eslint-disable-line react-hooks/exhaustive-deps

  return { agents, loading, error, refetch: load }
}
