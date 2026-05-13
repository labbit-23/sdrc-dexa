import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
)

// ── Types matching the DB schema ─────────────────────────────────────────
export interface Patient {
  id: string
  pat_handle: string
  patient_id: string | null
  first_name: string | null
  last_name: string | null   // used as title
  dob: string | null
  gender: string | null
  ethnicity: string | null
  height_cm: number | null
  weight_kg: number | null
  physician: string | null
  created_at: string
}

export interface Scan {
  id: string
  patient_id: string
  scan_handle: string
  scan_date: string | null
  scanner_serial: string | null
  software: string | null
  xps_filename: string | null
  created_at: string
  // joined
  reports?: Report[]
  bmd_results?: BmdResult[]
}

export interface BmdResult {
  id: string
  scan_id: string
  site: string
  side: string | null
  bmd: number | null
  bmc: number | null
  area: number | null
  t_score: number | null
  z_score: number | null
  pct_ya: number | null
  source: string
}

export interface Report {
  id: string
  scan_id: string
  pdf_url: string | null
  generated_at: string
  generator_version: string | null
}

// ── Helpers ───────────────────────────────────────────────────────────────
export function classify(t: number | null): {
  label: string
  color: string
  bg: string
} {
  if (t === null) return { label: 'Unknown', color: '#555', bg: '#f3f4f6' }
  if (t >= -1.0)  return { label: 'Normal',       color: '#166534', bg: '#dcfce7' }
  if (t >= -2.5)  return { label: 'Osteopenia',   color: '#92400e', bg: '#fef3c7' }
  return               { label: 'Osteoporosis', color: '#991b1b', bg: '#fee2e2' }
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric'
  })
}

export function calcAge(dob: string | null, refDate?: string): string {
  if (!dob) return '—'
  const d = new Date(dob)
  const r = refDate ? new Date(refDate) : new Date()
  const age = (r.getTime() - d.getTime()) / (365.25 * 24 * 3600 * 1000)
  return age.toFixed(1)
}
