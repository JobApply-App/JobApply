import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('signup') }
}

export default function SignupLayout({ children }: { children: React.ReactNode }) {
  return children
}
