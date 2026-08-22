import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Accessibility Statement' }

export default function AccessibilityLayout({ children }: { children: React.ReactNode }) {
  return children
}
