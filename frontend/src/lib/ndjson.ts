/**
 * Incremental newline-delimited JSON (NDJSON) line splitter.
 *
 * Pure, dependency-free, and independently testable — no fetch/ReadableStream
 * involved. Feed it decoded text chunks (in the order they arrive) via
 * push(); it buffers any trailing partial line across calls and returns only
 * the lines that are now complete. Call flush() once after the source ends
 * to retrieve a final line that had no trailing newline.
 *
 * Handles CRLF line endings by trimming a trailing \r from each returned
 * line — servers/proxies that normalize to \r\n must not break parsing.
 */
export class NdjsonLineSplitter {
  private buffer = ''

  /** Feed one decoded text chunk; returns zero or more now-complete lines
   *  (newline-terminated), each with any trailing \r stripped. Splits ONLY
   *  on \n — a lone \r is never treated as a line boundary. */
  push(chunk: string): string[] {
    this.buffer += chunk
    const lines: string[] = []
    let newlineIndex: number
    while ((newlineIndex = this.buffer.indexOf('\n')) !== -1) {
      let line = this.buffer.slice(0, newlineIndex)
      this.buffer = this.buffer.slice(newlineIndex + 1)
      if (line.endsWith('\r')) line = line.slice(0, -1)
      lines.push(line)
    }
    return lines
  }

  /** Call once after the source is exhausted — returns the final
   *  unterminated line (trailing \r stripped, same as push()), or null if
   *  nothing was left buffered. */
  flush(): string | null {
    const rest = this.buffer
    this.buffer = ''
    if (!rest) return null
    return rest.endsWith('\r') ? rest.slice(0, -1) : rest
  }
}
