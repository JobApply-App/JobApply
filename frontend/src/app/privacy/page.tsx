import type { Metadata } from 'next'
import { pageTitle } from '@/lib/pageTitle'
import { PrivacyContent } from './content'

// Stays a server component so `metadata` still applies; the locale-dependent
// body is a client component below it.
export async function generateMetadata(): Promise<Metadata> {
  return { title: await pageTitle('privacy') }
}

export default function PrivacyPage() {
  return <PrivacyContent />
}
