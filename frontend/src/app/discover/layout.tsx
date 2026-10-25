import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('discover') }
}

export default function DiscoverLayout({ children }: { children: React.ReactNode }) {
  return children
}
