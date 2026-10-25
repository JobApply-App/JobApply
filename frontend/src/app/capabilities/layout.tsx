import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('capabilities') }
}

export default function CapabilitiesLayout({ children }: { children: React.ReactNode }) {
  return children
}
