'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { supabase, Scan, Patient, BmdResult, Report, classify, formatDate } from '../../../lib/supabase'
import TScoreBar from '../../../components/TScoreBar'
import PdfViewer from '../../../components/PdfViewer'

interface FullScan extends Scan {
  bmd_results: BmdResult[]
  reports: Report[]
  patients: Patient
}

const SITE_ORDER = ['L1', 'L2', 'L3', 'L4', 'L1-L4', 'Neck', 'Wards', 'Trochanter', 'InterTroch', 'Total']

export default function ScanDetail() {
  const { id } = useParams<{ id: string }>()
  const [scan, setScan] = useState<FullScan | null>(null)
  const [loading, setLoading] = useState(true)
  const [regenerating, setRegenerating] = useState(false)
  const [msg, setMsg] = useState('')

  async function load() {
    const { data, error } = await supabase
      .from('scans')
      .select('*, bmd_results(*), reports(*), patients(*)')
      .eq('id', id)
      .single()
    if (data) setScan(data as FullScan)
    setLoading(false)
  }

  useEffect(() => { load() }, [id])

  async function regenerate() {
    setRegenerating(true)
    setMsg('')
    const res = await fetch('/api/regenerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scan_id: id, scan_handle: scan?.scan_handle }),
    })
    const json = await res.json()
    setMsg(json.ok ? 'Report regenerated.' : json.error || 'Error regenerating.')
    if (json.ok) load()
    setRegenerating(false)
  }

  if (loading) return <div className="p-8 text-gray-400">Loading…</div>
  if (!scan) return <div className="p-8 text-gray-500">Scan not found.</div>

  const patient = scan.patients
  const report = scan.reports?.[0]
  const results = scan.bmd_results

  // Group by side
  const spine  = results.filter(r => r.side === null)
  const lfemur = results.filter(r => r.side === 'left')
  const rfemur = results.filter(r => r.side === 'right')

  function sortSites(rows: BmdResult[]) {
    return [...rows].sort((a, b) =>
      SITE_ORDER.indexOf(a.site) - SITE_ORDER.indexOf(b.site)
    )
  }

  const allTs = results.map(r => r.t_score).filter(t => t !== null) as number[]
  const wt = allTs.length ? Math.min(...allTs) : null
  const cls = classify(wt)

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-[#0D1B2A] text-white shadow">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center gap-3 flex-wrap">
          <Link href="/" className="text-[#0D7377] hover:text-teal-300 text-sm">← Patients</Link>
          <span className="text-gray-600">/</span>
          <Link href={`/patients/${patient?.id}`}
                className="text-[#0D7377] hover:text-teal-300 text-sm">
            {patient?.last_name} {patient?.first_name}
          </Link>
          <span className="text-gray-600">/</span>
          <span className="font-semibold text-sm">{formatDate(scan.scan_date)}</span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-6">
        {/* Overall status */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Overall Assessment</p>
              <p className="text-2xl font-bold" style={{ color: cls.color }}>
                {cls.label}
              </p>
              {wt !== null && (
                <p className="text-sm text-gray-500 mt-1">Worst T-score: {wt.toFixed(1)}</p>
              )}
            </div>
            <div className="flex flex-col gap-2">
              {report?.pdf_url ? (
                <a
                  href={report.pdf_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 bg-[#0D7377] text-white text-sm
                             font-medium px-4 py-2 rounded-lg hover:bg-teal-700"
                >
                  📄 Open PDF Report
                </a>
              ) : (
                <span className="text-sm text-gray-400">No PDF available</span>
              )}
              <button
                onClick={regenerate}
                disabled={regenerating}
                className="text-sm text-[#0D7377] border border-[#0D7377] px-4 py-2
                           rounded-lg hover:bg-teal-50 disabled:opacity-50"
              >
                {regenerating ? 'Regenerating…' : '↺ Regenerate PDF'}
              </button>
              {msg && <p className="text-xs text-gray-500">{msg}</p>}
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-400">
            Scan date: {formatDate(scan.scan_date)}  •  {scan.scanner_serial}  •  {scan.software}
          </div>
        </div>

        {/* T-score gauges */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <h2 className="font-bold text-[#0D1B2A] mb-4">T-Score Overview</h2>
          <div className="space-y-3">
            {[
              { label: 'AP Spine L1–L4', row: spine.find(r => r.site === 'L1-L4') },
              { label: 'Left Femur Neck', row: lfemur.find(r => r.site === 'Neck') },
              { label: 'Right Femur Neck', row: rfemur.find(r => r.site === 'Neck') },
            ].map(({ label, row }) => row && (
              <TScoreBar key={label} label={label} t={row.t_score} bmd={row.bmd} />
            ))}
          </div>
        </div>

        {/* Results tables */}
        {[
          { title: 'AP Spine', rows: sortSites(spine) },
          { title: 'Left Hip / Femur', rows: sortSites(lfemur) },
          { title: 'Right Hip / Femur', rows: sortSites(rfemur) },
        ].map(({ title, rows }) => rows.length > 0 && (
          <div key={title} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
            <h2 className="font-bold text-[#0D1B2A] mb-3">{title}</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-[#0D7377] text-white text-xs">
                    {['Site', 'BMD (g/cm²)', 'T-Score', 'Z-Score', '%YA', 'BMC (g)', 'Area (cm²)', 'Source'].map(h => (
                      <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const rc = classify(r.t_score)
                    return (
                      <tr key={r.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                        <td className="px-3 py-2 font-medium text-gray-800">{r.site}</td>
                        <td className="px-3 py-2 text-right">{r.bmd?.toFixed(3) ?? '—'}</td>
                        <td className="px-3 py-2 text-right">
                          {r.t_score !== null ? (
                            <span
                              className="inline-block px-2 py-0.5 rounded-full text-xs font-bold"
                              style={{ color: rc.color, backgroundColor: rc.bg }}
                            >
                              {r.t_score >= 0 ? '+' : ''}{r.t_score.toFixed(1)}
                            </span>
                          ) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {r.z_score !== null ? `${r.z_score >= 0 ? '+' : ''}${r.z_score.toFixed(1)}` : '—'}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {r.pct_ya !== null ? `${r.pct_ya.toFixed(1)}%` : '—'}
                        </td>
                        <td className="px-3 py-2 text-right">{r.bmc?.toFixed(2) ?? '—'}</td>
                        <td className="px-3 py-2 text-right">{r.area?.toFixed(2) ?? '—'}</td>
                        <td className="px-3 py-2 text-xs text-gray-400">{r.source}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}

        {/* Inline PDF viewer */}
        {report?.pdf_url && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
            <h2 className="font-bold text-[#0D1B2A] mb-3">PDF Report</h2>
            <PdfViewer url={report.pdf_url} />
          </div>
        )}
      </main>
    </div>
  )
}
