import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('profile_builder') }
}

export default function ProfileBuilderLayout({ children }: { children: React.ReactNode }) {
  return children
}
