import { redirect } from 'next/navigation'

// The Capabilities page is now a section of the Profile page (Ron, 2026-11-27).
// Kept as a redirect so bookmarks and older links still land somewhere useful.
export default function CapabilitiesPage() {
  redirect('/profile')
}
