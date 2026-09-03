'use client'

import { useRouter } from 'next/navigation'
import { Header }    from '@/components/Header'
import { Footer }    from '@/components/Footer'
import { LanguageSettings } from '@/components/LanguageSettings'
import AuthGuard from '@/components/AuthGuard'
import type { Tab } from '@/components/Header'

function SettingsContent() {
  const router = useRouter()

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
        <LanguageSettings />
      </main>

      <Footer />
    </div>
  )
}

export default function SettingsPage() {
  return <AuthGuard><SettingsContent /></AuthGuard>
}
