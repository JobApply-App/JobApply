import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('login') }
}

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children
}
