import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'

export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('onboarding') }
}

export default function OnboardingLayout({ children }: { children: React.ReactNode }) {
  return children
}
