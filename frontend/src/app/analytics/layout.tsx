import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('analytics') }
}

export default function AnalyticsLayout({ children }: { children: React.ReactNode }) {
  return children
}
