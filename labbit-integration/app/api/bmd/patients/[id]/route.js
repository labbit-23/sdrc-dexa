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

export async function GET(request, { params }) {
  const sb = getSupabase()
  const { id } = params

  const { data: patient, error: pErr } = await sb
    .from('bmd_patients')
    .select('*')
    .eq('id', id)
    .single()

  if (pErr) return NextResponse.json({ error: pErr.message }, { status: 404 })

  const { data: scans, error: sErr } = await sb
    .from('bmd_scans')
    .select(`
      id, scan_date, scanner_serial, software, xps_filename,
      bmd_results(site, side, bmd, t_score, z_score, bmc, area),
      bmd_reports(id, pdf_url, generated_at)
    `)
    .eq('patient_id', id)
    .order('scan_date', { ascending: false })

  if (sErr) return NextResponse.json({ error: sErr.message }, { status: 500 })

  // Add per-scan summary fields
  const enrichedScans = (scans || []).map(scan => {
    let worstT = null
    const results = scan.bmd_results || []

    for (const r of results) {
      if (r.t_score != null && (worstT === null || r.t_score < worstT)) {
        worstT = r.t_score
      }
    }

    // Spine summary: grab L1-L4 T-score
    const spineL14 = results.find(r => r.side === null && r.site === 'L1-L4')
    // Femur neck (left preferred, else right)
    const neckL = results.find(r => r.side === 'left' && r.site === 'Neck')
    const neckR = results.find(r => r.side === 'right' && r.site === 'Neck')
    const neck = neckL || neckR

    return {
      ...scan,
      worst_t: worstT,
      classification: classify(worstT),
      spine_l14_t: spineL14?.t_score ?? null,
      femur_neck_t: neck?.t_score ?? null,
      pdf_url: scan.bmd_reports?.[0]?.pdf_url ?? null,
    }
  })

  return NextResponse.json({ patient, scans: enrichedScans })
}
