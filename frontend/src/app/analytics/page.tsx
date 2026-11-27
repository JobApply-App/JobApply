import { redirect } from 'next/navigation'

// Analytics folded into Applications as "What works" (Ron 27.11). The old
// address still lands somewhere useful for anyone who kept it.
export default function AnalyticsPage() {
  redirect('/?tab=apps')
}
