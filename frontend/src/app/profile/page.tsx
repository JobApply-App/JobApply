'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { Header } from '@/components/Header'
import { ProfilePage } from '@/components/profile/ProfilePage'

export default function Profile() {
  const { user, loading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!loading && !user) router.replace('/login')
  }, [loading, user, router])

  if (loading || !user) return null

  return (
    <div className="min-h-screen bg-ja-bg flex flex-col">
      <Header />
      <main id="main" className="flex-1">
        <ProfilePage userId={user.id} />
      </main>
    </div>
  )
}
