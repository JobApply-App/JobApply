import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('complete_profile') }
}

export default function CompleteProfileLayout({ children }: { children: React.ReactNode }) {
  return children
}
