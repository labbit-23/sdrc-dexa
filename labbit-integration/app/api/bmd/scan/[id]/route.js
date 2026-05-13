import { createClient } from '@supabase/supabase-js'
import { NextResponse } from 'next/server'

function getSupabase() {
  return createClient(
    process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  )
}

export async function GET(request, { params }) {
  const sb = getSupabase()
  const { id } = params

  const { data: scan, error: sErr } = await sb
    .from('bmd_scans')
    .select(`
      id, scan_date, scanner_serial, software, xps_filename,
      patient_id,
      bmd_results(id, site, side, bmd, bmc, area, t_score, z_score, pct_ya, source),
      bmd_reports(id, pdf_url, generated_at, generator_version)
    `)
    .eq('id', id)
    .single()

  if (sErr) return NextResponse.json({ error: sErr.message }, { status: 404 })

  const { data: patient, error: pErr } = await sb
    .from('bmd_patients')
    .select('id, patient_id, first_name, last_name, dob, gender, height_cm, weight_kg, physician')
    .eq('id', scan.patient_id)
    .single()

  if (pErr) return NextResponse.json({ error: pErr.message }, { status: 500 })

  // Organise results by region
  const results = scan.bmd_results || []
  const spine = {}
  const leftFemur = {}
  const rightFemur = {}

  const SPINE_ORDER = ['L1', 'L2', 'L3', 'L4', 'L1-L2', 'L1-L3', 'L1-L4', 'L2-L3', 'L2-L4', 'L3-L4']
  const FEMUR_ORDER = ['Neck', 'Wards', 'Trochanter', 'InterTroch', 'Total']

  for (const r of results) {
    if (r.side === null) spine[r.site] = r
    else if (r.side === 'left') leftFemur[r.site] = r
    else if (r.side === 'right') rightFemur[r.site] = r
  }

  // Worst T-score and classification
  let worstT = null
  for (const r of results) {
    if (r.t_score != null && (worstT === null || r.t_score < worstT)) worstT = r.t_score
  }

  const classification = worstT == null ? null
    : worstT <= -2.5 ? 'Osteoporosis'
    : worstT <= -1.0 ? 'Osteopenia'
    : 'Normal'

  return NextResponse.json({
    patient,
    scan: {
      ...scan,
      worst_t: worstT,
      classification,
      pdf_url: scan.bmd_reports?.[0]?.pdf_url ?? null,
    },
    regions: {
      spine: SPINE_ORDER.filter(s => spine[s]).map(s => ({ site: s, side: null, ...spine[s] })),
      left_femur: FEMUR_ORDER.filter(s => leftFemur[s]).map(s => ({ site: s, side: 'left', ...leftFemur[s] })),
      right_femur: FEMUR_ORDER.filter(s => rightFemur[s]).map(s => ({ site: s, side: 'right', ...rightFemur[s] })),
    },
  })
}
