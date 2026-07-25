'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { useChat } from '@/contexts/ChatContext'
import { Header } from '@/components/Header'
import { CapabilitiesList } from '@/components/TrustDashboard'

function CapabilitiesFooter() {
  const { openEliya } = useChat()

  return (
    <footer className="border-t border-slate-800 mt-16">
      <div className="max-w-4xl mx-auto px-6 py-6 flex items-center justify-between gap-4 flex-wrap">
        <span className="text-[11px] text-slate-500">
          © {new Date().getFullYear()} JobApply
        </span>
        <nav className="flex items-center gap-5 text-[11.5px] text-slate-400">
          <a
            href="mailto:support@jobapply.ai"
            className="hover:text-slate-200 transition-colors"
          >
            Support
          </a>
          <a
            href="/terms"
            className="hover:text-slate-200 transition-colors"
          >
            Terms
          </a>
          <a
            href="/privacy"
            className="hover:text-slate-200 transition-colors"
          >
            Privacy
          </a>
          <button
            onClick={openEliya}
            className="hover:text-indigo-400 transition-colors font-medium"
          >
            Help &amp; Support
          </button>
        </nav>
      </div>
    </footer>
  )
}

export default function CapabilitiesPage() {
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
                Capabilities
              </h1>
              <p className="text-[13px] text-slate-500 mt-1.5">
                Every verified and unverified skill, trait, and domain in your profile
              </p>
            </div>
          </div>

          <CapabilitiesList userId={user.id} />
        </div>
      </main>

      {/* Footer */}
      <div className="bg-slate-900">
        <CapabilitiesFooter />
      </div>
    </div>
  )
}
