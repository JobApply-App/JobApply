/**
 * getConfidenceMatrix.ts
 *
 * Fetches the four-category Confidence Matrix from
 * GET /api/profile/{userId}/confidence-matrix
 * and returns data ready for recharts RadarChart.
 *
 * Categories: Technical | Product_Leadership | Data_Analysis | Customer_Success
 *
 * Source Weight Contract (enforced on the backend):
 *   cv_parse          → 0.40
 *   portfolio         → 0.80
 *   conversation_star → 0.90
 *   certification     → 0.70
 */

import { ensureFreshToken, getAuthHeaders } from './api'

// ── Types ─────────────────────────────────────────────────────────────────────

export type MatrixCategory =
  | 'Technical'
  | 'Product_Leadership'
  | 'Data_Analysis'
  | 'Customer_Success'

export interface RadarDatum {
  /** Display label on the radar axis (spaces replace underscores). */
  category: string
  /** Confidence score 0–100, two decimal places. */
  value: number
}

export interface EntityBreakdownItem {
  entity_id: string
  name: string
  category: MatrixCategory
  score: number
}

export interface ConfidenceMatrixResponse {
  user_id: string
  radar_data: RadarDatum[]
  entity_breakdown: EntityBreakdownItem[]
  computed_at: string
}

// ── Display label map ─────────────────────────────────────────────────────────
// Converts API category keys to human-friendly axis labels.

const CATEGORY_LABELS: Record<MatrixCategory, string> = {
  Technical:           'Technical',
  Product_Leadership:  'Product Leadership',
  Data_Analysis:       'Data Analysis',
  Customer_Success:    'Customer Success',
}

// ── Fetch function ────────────────────────────────────────────────────────────

/**
 * Fetch and format the Confidence Matrix for the given user.
 *
 * Returns radar_data with display-friendly category labels (spaces, not underscores).
 * Throws on HTTP error — callers should handle with try/catch or SWR error state.
 */
export async function getConfidenceMatrix(
  userId: string
): Promise<ConfidenceMatrixResponse> {
  // Populate the auth token before reading headers — this fetch fires at
  // mount, potentially before AuthContext has called setAuthToken(); without
  // this an empty Authorization header 401s and trips the global sign-out.
  await ensureFreshToken()
  const res = await fetch(`/api/profile/${userId}/confidence-matrix`, {
    headers: { ...getAuthHeaders() },
  })

  if (!res.ok) {
    throw new Error(`getConfidenceMatrix: HTTP ${res.status}`)
  }

  const data: ConfidenceMatrixResponse = await res.json()

  // Rewrite category keys to display labels for the RadarChart axis
  return {
    ...data,
    radar_data: data.radar_data.map(d => ({
      ...d,
      category: CATEGORY_LABELS[d.category as MatrixCategory] ?? d.category,
    })),
  }
}

// ── React hook ────────────────────────────────────────────────────────────────

import { useState, useEffect } from 'react'

interface UseConfidenceMatrixResult {
  radarData: RadarDatum[]
  breakdown: EntityBreakdownItem[]
  loading: boolean
  error: string | null
  refetch: () => void
}

/**
 * Hook: fetches and caches the Confidence Matrix for `userId`.
 * Re-fetches whenever `userId` changes or `refetch()` is called.
 *
 * Example:
 *   const { radarData, loading } = useConfidenceMatrix(user.id)
 *   <RadarChart data={radarData} />
 */
export function useConfidenceMatrix(userId: string | null): UseConfidenceMatrixResult {
  const [radarData, setRadarData]   = useState<RadarDatum[]>([])
  const [breakdown, setBreakdown]   = useState<EntityBreakdownItem[]>([])
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState<string | null>(null)
  const [tick, setTick]             = useState(0)

  useEffect(() => {
    if (!userId) return

    let cancelled = false
    setLoading(true)
    setError(null)

    getConfidenceMatrix(userId)
      .then(data => {
        if (cancelled) return
        setRadarData(data.radar_data)
        setBreakdown(data.entity_breakdown)
      })
      .catch(err => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [userId, tick])

  return {
    radarData,
    breakdown,
    loading,
    error,
    refetch: () => setTick(t => t + 1),
  }
}
