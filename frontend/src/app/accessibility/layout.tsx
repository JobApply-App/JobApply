import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('accessibility') }
}

export default function AccessibilityLayout({ children }: { children: React.ReactNode }) {
  return children
}
