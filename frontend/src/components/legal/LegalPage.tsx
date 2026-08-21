import Link from 'next/link'
import { TOKENS } from '@/lib/tokens'

/**
 * Shared shell for /terms and /privacy.
 *
 * Deliberately a plain server component with no auth dependency — these
 * pages must be readable by a signed-out visitor deciding whether to sign
 * up, not just an authenticated user.
 */
export function LegalPage({
  title, updated, children,
}: {
  title:   string
  updated: string
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b" style={{ borderColor: TOKENS.color.line }}>
        <div className="max-w-2xl mx-auto px-6 py-5 flex items-center justify-between">
          <Link href="/" className="text-lg font-extrabold tracking-tight"
            style={{ color: TOKENS.color.ink }}>
            JobApply
          </Link>
          <Link href="/signup" className="text-[13px] font-medium hover:underline"
            style={{ color: TOKENS.color.primary }}>
            Back to sign up
          </Link>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-10">
        <div
          className="rounded-2xl px-5 py-4 mb-8 text-[13px] leading-relaxed"
          style={{ background: TOKENS.color.primarySoft, border: `1px solid ${TOKENS.color.line}` }}
        >
          <strong style={{ color: TOKENS.color.ink }}>Draft — pending legal review.</strong>{' '}
          <span style={{ color: TOKENS.color.ink2 }}>
            This page describes what JobApply actually does with your data, in plain language,
            to the best of our current knowledge. It has not yet been reviewed by a lawyer and
            should not be treated as a final, binding legal document until it has.
          </span>
        </div>

        <h1 className="text-3xl font-extrabold tracking-tight mb-1" style={{ color: TOKENS.color.ink }}>
          {title}
        </h1>
        <p className="text-[13px] mb-8" style={{ color: TOKENS.color.muted }}>
          Last updated {updated}
        </p>

        <div className="prose-legal">{children}</div>
      </main>

      <footer className="border-t mt-16" style={{ borderColor: TOKENS.color.line }}>
        <div className="max-w-2xl mx-auto px-6 py-6 flex items-center justify-between text-[12px]"
          style={{ color: TOKENS.color.muted }}>
          <span>&copy; {new Date().getFullYear()} JobApply</span>
          <a href="mailto:support@jobapply.ai" className="hover:underline">Contact</a>
        </div>
      </footer>

      <style>{`
        .prose-legal h2 {
          font-size: 1.05rem; font-weight: 700; margin: 2rem 0 0.6rem;
          color: ${TOKENS.color.ink};
        }
        .prose-legal p, .prose-legal li {
          font-size: 14px; line-height: 1.7; color: ${TOKENS.color.ink2};
        }
        .prose-legal ul { margin: 0.5rem 0 1rem; padding-inline-start: 1.25rem; }
        .prose-legal li { margin-bottom: 0.35rem; }
        .prose-legal strong { color: ${TOKENS.color.ink}; }
      `}</style>
    </div>
  )
}
