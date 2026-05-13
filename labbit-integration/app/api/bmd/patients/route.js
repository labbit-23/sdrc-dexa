import { createClient } from '@supabase/supabase-js'
import { NextResponse } from 'next/server'

function getSupabase() {
  return createClient(
    process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  )
}

function classify(worstT) {
  if (worstT == null) return null
  if (worstT <= -2.5) return 'Osteoporosis'
  if (worstT <= -1.0) return 'Osteopenia'
  return 'Normal'
}

export async function GET(request) {
  const { searchParams } = new URL(request.url)
  const q = (searchParams.get('q') || '').trim()

  const sb = getSupabase()

  let pq = sb
    .from('bmd_patients')
    .select('id, patient_id, first_name, last_name, dob, gender')
    .order('first_name')

  if (q) {
    pq = pq.or(
      `first_name.ilike.%${q}%,last_name.ilike.%${q}%,patient_id.ilike.%${q}%`
    )
  }

  const { data: patients, error: pErr } = await pq
  if (pErr) return NextResponse.json({ error: pErr.message }, { status: 500 })
  if (!patients.length) return NextResponse.json({ patients: [] })

  // Fetch latest scan + worst T-score for each patient in one query
  const ids = patients.map(p => p.id)
  const { data: scans, error: sErr } = await sb
    .from('bmd_scans')
    .select('id, patient_id, scan_date, bmd_results(t_score)')
    .in('patient_id', ids)
    .order('scan_date', { ascending: false })

  if (sErr) return NextResponse.json({ error: sErr.message }, { status: 500 })

  // Build per-patient summary
  const scansByPatient = {}
  for (const scan of (scans || [])) {
    if (!scansByPatient[scan.patient_id]) scansByPatient[scan.patient_id] = []
    scansByPatient[scan.patient_id].push(scan)
  }

  const result = patients.map(p => {
    const pScans = scansByPatient[p.id] || []
    const lastScan = pScans[0] || null

    let worstT = null
    for (const scan of pScans) {
      for (const r of (scan.bmd_results || [])) {
        if (r.t_score != null && (worstT === null || r.t_score < worstT)) {
          worstT = r.t_score
        }
      }
    }

    return {
      ...p,
      scan_count: pScans.length,
      last_scan_date: lastScan?.scan_date ?? null,
      worst_t: worstT,
      classification: classify(worstT),
    }
  })

  return NextResponse.json({ patients: result })
}
