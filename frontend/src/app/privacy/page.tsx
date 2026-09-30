import { PrivacyContent } from './content'

// Stays a server component so `metadata` still applies; the locale-dependent
// body is a client component below it.
export const metadata = { title: 'Privacy Policy' }

export default function PrivacyPage() {
  return <PrivacyContent />
}
