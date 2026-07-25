'use client'

import { useRouter } from 'next/navigation'
import { Header }    from '@/components/Header'
import { Footer }    from '@/components/Footer'
import { ScraperPreview } from '@/components/ScraperPreview'
import AuthGuard from '@/components/AuthGuard'
import type { Tab } from '@/components/Header'

function AtsPreviewContent() {
  const router = useRouter()

  // Main-nav tab clicks route back to the home shell with the tab preselected.
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
        <ScraperPreview />
      </main>

      <Footer />
    </div>
  )
}

export default function AtsPreviewPage() {
  return <AuthGuard><AtsPreviewContent /></AuthGuard>
}
