'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { supabase, Patient, Scan, BmdResult, classify, formatDate, calcAge } from '../lib/supabase'

interface PatientRow extends Patient {
  scans: (Scan & { bmd_results: BmdResult[] })[]
}

export default function PatientList() {
  const [patients, setPatients] = useState<PatientRow[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)

  const loadPatients = useCallback(async (q: string) => {
    setLoading(true)
    let req = supabase
      .from('patients')
      .select(`
        *,
        scans(
          id, scan_date, scan_handle,
          bmd_results(site, side, t_score)
        )
      `)
      .order('first_name')
      .limit(200)

    if (q.trim()) {
      req = req.or(
        `first_name.ilike.%${q}%,patient_id.ilike.%${q}%`
      )
    }

    const { data, error } = await req
    if (!error && data) setPatients(data as PatientRow[])
    setLoading(false)
  }, [])

  useEffect(() => { loadPatients('') }, [loadPatients])
  useEffect(() => {
    const t = setTimeout(() => loadPatients(query), 300)
    return () => clearTimeout(t)
  }, [query, loadPatients])

  // Realtime: refresh on new scan
  useEffect(() => {
    const channel = supabase
      .channel('scans-list')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'scans' },
          () => loadPatients(query))
      .subscribe()
    return () => { supabase.removeChannel(channel) }
  }, [query, loadPatients])

  function worstT(scans: PatientRow['scans']): number | null {
    const latest = scans[0]
    if (!latest) return null
    const ts = latest.bmd_results.map(r => r.t_score).filter(t => t !== null) as number[]
    return ts.length ? Math.min(...ts) : null
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-[#0D1B2A] text-white shadow">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/labit-logo.png" alt="Labit"
              style={{ height: 32, width: 110, objectFit: 'cover', objectPosition: 'left center', borderRadius: 4, display: 'block' }}
            />
            <div className="border-l border-gray-700 pl-3">
              <p className="text-xs text-gray-400">DEXA / BMD Report System</p>
            </div>
          </div>
          <span className="text-sm text-gray-300">
            {patients.length} patient{patients.length !== 1 ? 's' : ''}
          </span>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6">
        {/* Search */}
        <input
          type="text"
          placeholder="Search by name or patient ID…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          className="w-full mb-6 px-4 py-3 rounded-lg border border-gray-200 shadow-sm
                     focus:outline-none focus:ring-2 focus:ring-[#0D7377]"
        />

        {loading ? (
          <div className="text-center text-gray-400 py-12">Loading…</div>
        ) : patients.length === 0 ? (
          <div className="text-center text-gray-400 py-12">No patients found</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {patients.map(p => {
              const wt = worstT(p.scans || [])
              const cls = classify(wt)
              const lastScan = p.scans?.[0]
              return (
                <Link
                  key={p.id}
                  href={`/patients/${p.id}`}
                  className="block bg-white rounded-xl shadow-sm hover:shadow-md transition-shadow
                             border border-gray-100 overflow-hidden"
                >
                  {/* Coloured top bar */}
                  <div className="h-1" style={{ backgroundColor: cls.color }} />
                  <div className="p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <p className="font-semibold text-gray-900">
                          {p.last_name} {p.first_name}
                        </p>
                        <p className="text-xs text-gray-500">PID: {p.patient_id || '—'}</p>
                      </div>
                      {wt !== null && (
                        <span
                          className="text-xs font-bold px-2 py-1 rounded-full"
                          style={{ color: cls.color, backgroundColor: cls.bg }}
                        >
                          {cls.label}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 space-y-0.5">
                      <p>Age: {calcAge(p.dob, lastScan?.scan_date ?? undefined)} yrs  •  {p.gender}</p>
                      {lastScan && (
                        <p>Last scan: {formatDate(lastScan.scan_date)}</p>
                      )}
                      {wt !== null && (
                        <p>Worst T-score: <span className="font-medium">{wt.toFixed(1)}</span></p>
                      )}
                    </div>
                  </div>
                </Link>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
