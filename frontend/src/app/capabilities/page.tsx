'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { useI18n } from '@/contexts/I18nContext'
import { useChat } from '@/contexts/ChatContext'
import { Header } from '@/components/Header'
import { CapabilitiesList } from '@/components/TrustDashboard'

export default function CapabilitiesPage() {
  const T = useI18n().t.trust
  const { user, loading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!loading && !user) router.replace('/login')
  }, [loading, user, router])

  if (loading || !user) return null

  return (
    <div className="min-h-screen bg-ja-bg flex flex-col">
      {/* Global nav — sticky, matches all other pages */}
      <Header />

      {/* Page content */}
      <main className="flex-1">
        <div className="max-w-4xl mx-auto px-6 py-10 space-y-8">

          {/* Page header */}
          <div className="flex items-end justify-between gap-4">
            <div>
              <h1 className="text-[24px] font-bold text-slate-900 tracking-tight leading-none">
                {T.caps_title}
              </h1>
              <p className="text-[13px] text-slate-500 mt-1.5">
                {T.caps_subtitle}
              </p>
            </div>
          </div>

          <CapabilitiesList userId={user.id} />
        </div>
      </main>

    </div>
  )
}
