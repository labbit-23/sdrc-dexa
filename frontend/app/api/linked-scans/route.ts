export const dynamic = 'force-dynamic'

import { getServiceClient } from '@/lib/supabase'

export async function GET(req: Request) {
  try {
    const url = new URL(req.url)
    const patientId = url.searchParams.get('patient_id')

    if (!patientId) {
      return Response.json({ error: 'Missing patient_id' }, { status: 400 })
    }

    const sb = getServiceClient()

    // Get patient's MRN first
    const { data: patient, error: patErr } = await sb
      .from('bmd_patients')
      .select('id, patient_id')
      .eq('patient_id', patientId)
      .single()

    if (patErr || !patient) {
      return Response.json({ error: 'Patient not found' }, { status: 404 })
    }

    // Get all scans for this patient (excluding archived ones)
    const { data: allScans, error: scanErr } = await sb
      .from('bmd_scans')
      .select('id, scan_date, scan_type')
      .eq('patient_id', patient.id)
      .eq('is_archived', false) // Exclude archived scans
      .order('scan_date', { ascending: false })

    if (scanErr) {
      return Response.json({ error: scanErr.message }, { status: 500 })
    }

    // Deduplicate: keep only one per (scan_date, scan_type) combo
    const seen = new Set()
    const deduped = (allScans || []).filter(s => {
      const key = `${s.scan_date}|${s.scan_type}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })

    // "Linked" means 2+ scans on DIFFERENT dates
    // If only 1 unique date, it's not linked (nothing to link to)
    const uniqueDates = new Set(deduped.map(s => s.scan_date))
    if (uniqueDates.size < 2) {
      return Response.json([])
    }

    return Response.json(deduped)
  } catch (e) {
    console.error('Linked scans error:', e)
    return Response.json({ error: (e as Error).message }, { status: 500 })
  }
}
