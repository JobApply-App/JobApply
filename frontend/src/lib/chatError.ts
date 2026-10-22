/**
 * Error thrown by the chat stream readers. It carries the HTTP status (when
 * there was one) so the UI can pick a message in the user's language instead
 * of showing the server's text. That text is English and technical ("An
 * unexpected error occurred while contacting the AI service."), and testers
 * saw it as-is in the middle of a Hebrew conversation.
 */
export class ChatStreamError extends Error {
  status?: number
  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ChatStreamError'
    this.status = status
  }
}

/** The localised text for a chat failure. Server detail goes to the console only. */
export function chatErrorText(err: unknown, texts: { generic: string; rateLimited: string }): string {
  if (err) console.error('[chat] stream failed:', err)
  return err instanceof ChatStreamError && err.status === 429 ? texts.rateLimited : texts.generic
}
