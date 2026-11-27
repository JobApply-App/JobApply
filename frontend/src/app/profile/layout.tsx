import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('profile') }
}

export default function ProfileLayout({ children }: { children: React.ReactNode }) {
  return children
}
