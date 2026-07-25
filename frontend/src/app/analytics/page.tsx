'use client'

import { useRouter } from 'next/navigation'
import { Header }    from '@/components/Header'
import { Footer }    from '@/components/Footer'
import { AnalyticsDashboard } from '@/components/AnalyticsDashboard'
import AuthGuard from '@/components/AuthGuard'
import type { Tab } from '@/components/Header'

function AnalyticsContent() {
  const router = useRouter()

  // When the user clicks a main-nav tab, send them back to the home shell
  // with the correct tab pre-selected via a query param.
  const handleSetTab = (t: Tab) => {
    router.push(`/?tab=${t}`)
  }

  return (
    <div className="min-h-screen bg-[#FBFBFA]">
      <Header
        tab="overview"
        setTab={handleSetTab}
        onOpenControls={() => {}}
      />

      <main className="max-w-content mx-auto px-6 py-8">
        <AnalyticsDashboard onGoToMatches={() => router.push('/?tab=feed')} />
      </main>

      <Footer />
    </div>
  )
}

export default function AnalyticsPage() {
  return <AuthGuard><AnalyticsContent /></AuthGuard>
}
