import { createClient } from '@supabase/supabase-js'

// 2026-08-11: shared client so the request timeout only needs fixing in one
// place -- previously duplicated across scan/[id], patients, and
// patients/[id] routes, exactly the drift that caused an incident in
// labit-main's equivalent duplicated clients.
export function getSupabase() {
  return createClient(
    process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    { global: { fetch: (url, options = {}) => fetch(url, { ...options, signal: AbortSignal.timeout(15000) }) } }
  )
}
