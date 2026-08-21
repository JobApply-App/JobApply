import { LegalPage } from '@/components/legal/LegalPage'

export const metadata = { title: 'Privacy Policy — JobApply' }

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="August 2026">
      <h2>What we collect</h2>
      <ul>
        <li><strong>Account info</strong> — email address and name, from email/password sign-up
          or Google sign-in.</li>
        <li><strong>Your career data</strong> — anything you provide to build your profile: work
          history, education, skills, uploaded CVs, and information imported from LinkedIn if you
          choose to connect it.</li>
        <li><strong>Application activity</strong> — the jobs you view, save, or apply to, and the
          status of those applications as you (or, if enabled, a forwarded recruiter email) update them.</li>
        <li><strong>Conversations with the AI assistant</strong> — messages you send to Ariel and
          the context needed to answer them.</li>
        <li><strong>Basic usage data</strong> — the kind any web app collects to keep the service
          running (timestamps, error logs, rough activity counts).</li>
      </ul>

      <h2>How we use it</h2>
      <ul>
        <li>To generate tailored CVs, fit scores, and outreach messages personalized to you and a
          specific job.</li>
        <li>To run your job feed and match you against new postings.</li>
        <li>To operate the AI assistant.</li>
        <li>To maintain and improve the service (debugging, abuse prevention).</li>
      </ul>
      <p>We do not sell your data.</p>

      <h2>Who else sees it</h2>
      <ul>
        <li><strong>Anthropic and, where enabled, Google</strong> — process your profile and job
          content to generate CVs, scores, and chat replies. They receive what&apos;s needed for
          that specific request, not your full account.</li>
        <li><strong>Supabase</strong> — hosts our database and handles authentication. Your
          account and profile data lives there.</li>
        <li>We don&apos;t share your data with employers or third parties for marketing. A
          tailored CV is only sent where you choose to send it.</li>
      </ul>

      <h2>AI processing</h2>
      <p>
        Generating a tailored CV, a match score, or a chat reply means sending relevant parts of
        your profile to an AI provider (Anthropic, and optionally Google Gemini) for that specific
        request. We don&apos;t currently offer a way to use JobApply&apos;s core features without
        this.
      </p>

      <h2>Your choices</h2>
      <ul>
        <li>You can edit or delete individual profile fields, CV entries, and application records
          from within the product.</li>
        <li>
          Full account deletion and a complete data export are not yet available as self-service
          actions — <strong>if you want either, contact us directly</strong> and we&apos;ll handle
          it manually while that capability is being built.
        </li>
      </ul>

      <h2>Security</h2>
      <p>
        Your session is authenticated via signed tokens; application data is scoped to your
        account. As with any online service, no system is perfectly secure, and we can&apos;t
        guarantee absolute protection against every possible attack.
      </p>

      <h2>Changes</h2>
      <p>
        We may update this policy as the product changes. Material changes will be reflected here
        with an updated date.
      </p>

      <h2>Contact</h2>
      <p>
        Questions about this policy, or a request to delete your account or export your data:{' '}
        <a href="mailto:support@jobapply.ai">support@jobapply.ai</a>.
      </p>
    </LegalPage>
  )
}
