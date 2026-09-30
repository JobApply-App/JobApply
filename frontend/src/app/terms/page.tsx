import { TermsContent } from './content'

// Stays a server component so `metadata` still applies; the locale-dependent
// body is a client component below it.
export const metadata = { title: 'Terms of Service' }

export default function TermsPage() {
  return <TermsContent />
}
