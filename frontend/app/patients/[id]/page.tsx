'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { supabase, Patient, Scan, BmdResult, Report, classify, formatDate, calcAge } from '../../../lib/supabase'
import BmdChart from '../../../components/BmdChart'

interface FullScan extends Scan {
  bmd_results: BmdResult[]
  reports: Report[]
}

export default function PatientDetail() {
  const { id } = useParams<{ id: string }>()
  const [patient, setPatient] = useState<Patient | null>(null)
  const [scans, setScans] = useState<FullScan[]>([])
  const [loading, setLoading] = useState(true)
  const [newScan, setNewScan] = useState(false)

  async function load() {
    const [pRes, sRes] = await Promise.all([
      supabase.from('patients').select('*').eq('id', id).single(),
      supabase
        .from('scans')
        .select('*, bmd_results(*), reports(*)')
        .eq('patient_id', id)
        .order('scan_date', { ascending: false }),
    ])
    if (pRes.data) setPatient(pRes.data)
    if (sRes.data) setScans(sRes.data as FullScan[])
    setLoading(false)
  }

  useEffect(() => { load() }, [id])

  // Realtime: notify when worker uploads new scan
  useEffect(() => {
    const channel = supabase
      .channel(`patient-${id}`)
      .on('postgres_changes',
          { event: 'INSERT', schema: 'public', table: 'scans', filter: `patient_id=eq.${id}` },
          () => { setNewScan(true); load() })
      .subscribe()
    return () => { supabase.removeChannel(channel) }
  }, [id])

  if (loading) return <div className="p-8 text-gray-400">Loading…</div>
  if (!patient) return <div className="p-8 text-gray-500">Patient not found.</div>

  const bmi = patient.height_cm && patient.weight_kg
    ? (patient.weight_kg / (patient.height_cm / 100) ** 2).toFixed(1)
    : null

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-[#0D1B2A] text-white shadow">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center gap-3">
          <Link href="/" className="text-[#0D7377] hover:text-teal-300 text-sm">← Patients</Link>
          <span className="text-gray-600">/</span>
          <h1 className="font-semibold">
            {patient.last_name} {patient.first_name}
          </h1>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-6">
        {newScan && (
          <div className="bg-green-50 border border-green-200 text-green-800 rounded-lg px-4 py-3 text-sm">
            New scan available — page updated automatically.
          </div>
        )}

        {/* Demographics card */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <h2 className="font-bold text-[#0D1B2A] mb-3 text-base">Patient Details</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            {[
              ['Patient ID', patient.patient_id],
              ['Date of Birth', formatDate(patient.dob)],
              ['Age', `${calcAge(patient.dob)} yrs`],
              ['Sex', patient.gender],
              ['Height', patient.height_cm ? `${patient.height_cm} cm` : '—'],
              ['Weight', patient.weight_kg ? `${patient.weight_kg} kg` : '—'],
              ['BMI', bmi ? `${bmi} kg/m²` : '—'],
              ['Physician', patient.physician],
            ].map(([label, value]) => (
              <div key={label as string}>
                <p className="text-xs text-gray-400 uppercase tracking-wide">{label}</p>
                <p className="font-medium text-gray-800">{value || '—'}</p>
              </div>
            ))}
          </div>
        </div>

        {/* BMD trend chart */}
        {scans.length > 1 && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
            <h2 className="font-bold text-[#0D1B2A] mb-3">BMD Trend</h2>
            <BmdChart scans={scans} />
          </div>
        )}

        {/* Scan history */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <h2 className="font-bold text-[#0D1B2A] mb-3">Scan History</h2>
          {scans.length === 0 ? (
            <p className="text-gray-400 text-sm">No scans on record.</p>
          ) : (
            <div className="space-y-3">
              {scans.map(s => {
                const ts = s.bmd_results.map(r => r.t_score).filter(t => t !== null) as number[]
                const wt = ts.length ? Math.min(...ts) : null
                const cls = classify(wt)
                const report = s.reports?.[0]
                return (
                  <Link
                    key={s.id}
                    href={`/scans/${s.id}`}
                    className="flex items-center justify-between rounded-lg border border-gray-100
                               px-4 py-3 hover:border-[#0D7377] hover:shadow-sm transition-all"
                  >
                    <div className="flex items-center gap-4">
                      <div>
                        <p className="font-medium text-sm text-gray-800">
                          {formatDate(s.scan_date)}
                        </p>
                        <p className="text-xs text-gray-400">{s.scanner_serial}  •  {s.software}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {wt !== null && (
                        <span
                          className="text-xs font-bold px-2 py-1 rounded-full"
                          style={{ color: cls.color, backgroundColor: cls.bg }}
                        >
                          {cls.label}  T={wt.toFixed(1)}
                        </span>
                      )}
                      {report?.pdf_url && (
                        <span className="text-xs text-[#0D7377] font-medium">PDF ↗</span>
                      )}
                    </div>
                  </Link>
                )
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
