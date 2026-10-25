import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('signing_in') }
}

export default function AuthCallbackLayout({ children }: { children: React.ReactNode }) {
  return children
}
