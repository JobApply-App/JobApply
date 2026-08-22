import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Build Your Profile' }

export default function ProfileBuilderLayout({ children }: { children: React.ReactNode }) {
  return children
}
