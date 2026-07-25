/**
 * Supabase browser client singleton.
 *
 * Reads NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY from the
 * environment.  Both variables must be present and well-formed for the client
 * to be created.  If either is absent or still holds a placeholder value the
 * client is null and authentication is unavailable.
 */
import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const supabaseUrl  = process.env.NEXT_PUBLIC_SUPABASE_URL  ?? ''
const supabaseAnon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ''

/**
 * Returns true only when both env vars are present AND look like real values:
 *   • URL must start with "https://" (rules out empty string and placeholders)
 *   • Anon key must start with "eyJ"  (all Supabase JWTs begin with this prefix)
 *
 * This prevents the client from being constructed with the commented-out
 * placeholder lines from .env.local, which would cause silent runtime errors.
 */
function _isConfigured(url: string, key: string): boolean {
  return url.startsWith('https://') && key.startsWith('eyJ')
}

export const SUPABASE_CONFIGURED = _isConfigured(supabaseUrl, supabaseAnon)

/**
 * Singleton Supabase browser client.
 * Null when SUPABASE_CONFIGURED is false — callers must guard before use.
 */
export const supabase: SupabaseClient | null = SUPABASE_CONFIGURED
  ? createClient(supabaseUrl, supabaseAnon)
  : null
