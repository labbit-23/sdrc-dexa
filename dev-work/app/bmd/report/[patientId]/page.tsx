'use client'

import { useState, useEffect } from 'react'

type SymmetryResult = { level: 'amber' | 'red'; items: string[] } | null

function computeSymmetry(raw: any): SymmetryResult {
  const snap = raw?.mdb_snapshot
  const compEntries = Object.values(snap?.composition ?? {}) as any[][]
  if (!compEntries.length) return null

  const BLABELS: Record<number, string> = {
    51: 'left_arm', 52: 'left_leg', 53: 'left_trunk', 54: 'left_total',
    55: 'right_arm', 56: 'right_leg', 57: 'right_trunk', 58: 'right_total',
  }
  const isTB = (rows: any[]) => rows.some(r => parseInt(r.label) === 7 && parseFloat(r.bone_mass || 0) > 0)
  const rows = compEntries.find(isTB) ?? compEntries[0]
  if (!rows) return null

  const b: Record<string, { fat_g: number; lean_g: number; bone_g: number }> = {}
  for (const row of rows) {
    const key = BLABELS[parseInt(row.label)]
    if (!key) continue
    b[key] = {
      fat_g:  Math.round(Math.abs(parseFloat(row.fat_mass)  || 0)),
      lean_g: Math.round(Math.abs(parseFloat(row.lean_mass) || 0)),
      bone_g: Math.round(Math.abs(parseFloat(row.bone_mass) || 0)),
    }
  }
  if (!b.left_arm) return null

  const asym = (l: number, r: number) => {
    const mx = Math.max(l, r); return mx > 0 ? +((Math.abs(l - r) / mx * 100).toFixed(1)) : 0
  }
  const sev = (pct: number, isArm: boolean): 'red' | 'amber' | null => {
    const [lo, hi] = isArm ? [15, 25] : [10, 15]
    return pct >= hi ? 'red' : pct >= lo ? 'amber' : null
  }

  const flags: { s: 'red' | 'amber'; text: string }[] = []
  const check = (lk: string, rk: string, label: string, isArm: boolean) => {
    const L = b[lk], R = b[rk]; if (!L || !R) return
    for (const [m, l, r] of [['lean', L.lean_g, R.lean_g], ['fat', L.fat_g, R.fat_g], ['bone', L.bone_g, R.bone_g]] as [string, number, number][]) {
      const p = asym(l, r), s = sev(p, isArm)
      if (s) flags.push({ s, text: `${label} ${m} ${p}%` })
    }
  }
  check('left_arm', 'right_arm', 'arm', true)
  check('left_leg', 'right_leg', 'leg', false)
  check('left_trunk', 'right_trunk', 'trunk', false)

  if (!flags.length) return null
  return {
    level: flags.some(f => f.s === 'red') ? 'red' : 'amber',
    items: flags.map(f => f.text),
  }
}

export default function ReportBrowserPage({
  params,
}: {
  params: { patientId: string }
}) {
  const { patientId } = params
  const [dark, setDark] = useState(true)
  const [letterhead, setLetterhead] = useState(false)
  const [fatMode, setFatMode] = useState(false)
  const [symmetry, setSymmetry] = useState<SymmetryResult>(null)

  useEffect(() => {
    fetch(`/api/bmd/data/${patientId}`)
      .then(r => r.ok ? r.json() : null)
      .then(raw => { if (raw) setSymmetry(computeSymmetry(raw)) })
      .catch(() => {})
  }, [patientId])

  const modeParam = fatMode ? '&mode=fat' : ''
  const renderUrl = letterhead
    ? `/bmd/render/${patientId}?dark=0&lh=1${modeParam}`
    : dark
      ? `/bmd/render/${patientId}?${modeParam ? modeParam.slice(1) : ''}`
      : `/bmd/render/${patientId}?dark=0${modeParam}`

  const btn = (href: string, label: string, style: React.CSSProperties) => (
    <a href={href} style={{ padding: '5px 14px', borderRadius: 5, fontSize: 12, fontWeight: 700, textDecoration: 'none', ...style }}>
      {label}
    </a>
  )

  return (
    <div style={{ position: 'fixed', inset: 0, background: '#0D1B2A', display: 'flex', flexDirection: 'column' }}>
      {/* Toolbar */}
      <div style={{
        height: 44, background: '#0f2235', borderBottom: '1px solid #1a3a55',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 16px', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/sdrc-logo.png" alt="SDRC" style={{ height: 28, width: 'auto', display: 'block', background: 'rgba(255,255,255,0.92)', borderRadius: 4, padding: '2px 6px' }} />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/labit-logo.png" alt="Labit" style={{ height: 24, width: 'auto', display: 'block' }} />
          <span style={{ fontSize: 11, color: '#4a7a99', borderLeft: '1px solid #1a3a55', paddingLeft: 10 }}>
            DEXA Report &nbsp;·&nbsp; {patientId}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={() => setFatMode(m => !m)}
            style={{
              padding: '5px 14px', borderRadius: 5, fontSize: 12, fontWeight: 600,
              background: fatMode ? '#1a0a2e' : '#0a1f30',
              color: fatMode ? '#ce93d8' : '#14a8ae',
              border: `1px solid ${fatMode ? '#9c27b044' : '#14a8ae44'}`,
              cursor: 'pointer',
            }}
          >
            {fatMode ? 'Fat Analysis' : 'Athletic'}
          </button>
          <button
            onClick={() => { setDark(d => !d); setLetterhead(false) }}
            style={{
              padding: '5px 14px', borderRadius: 5, fontSize: 12, fontWeight: 600,
              background: dark && !letterhead ? '#1a3a55' : '#e8f4fb',
              color: dark && !letterhead ? '#14a8ae' : '#0D7377',
              border: `1px solid ${dark && !letterhead ? '#14a8ae44' : '#0D737744'}`,
              cursor: 'pointer',
            }}
          >
            {dark && !letterhead ? '☀ Light' : '🌙 Dark'}
          </button>
          <button
            onClick={() => setLetterhead(l => !l)}
            style={{
              padding: '5px 14px', borderRadius: 5, fontSize: 12, fontWeight: 600,
              background: letterhead ? '#fff3e0' : '#1a3a55',
              color: letterhead ? '#b45309' : '#CFD8DC',
              border: `1px solid ${letterhead ? '#f59e0b66' : '#1a3a55'}`,
              cursor: 'pointer',
            }}
          >
            {letterhead ? '✕ Exit letterhead' : '📄 Letterhead'}
          </button>
          <a
            href={renderUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              padding: '5px 14px', borderRadius: 5, fontSize: 12, fontWeight: 600,
              background: '#1a3a55', color: '#CFD8DC', textDecoration: 'none',
            }}
          >
            Open in tab
          </a>
          {btn(`/api/bmd/pdf?patient=${patientId}${modeParam}`, '↓ PDF (Print)', { background: '#0D7377', color: '#fff' })}
          {btn(`/api/bmd/pdf-dark?patient=${patientId}${modeParam}`, '↓ PDF (Dark)', { background: '#1a3a55', color: '#00BCD4' })}
          {btn(`/api/bmd/pdf-letterhead?patient=${patientId}${modeParam}`, '↓ PDF (Letterhead)', { background: '#92400e', color: '#fef3c7' })}
        </div>
      </div>

      {/* Symmetry ROI warning banner — screen only, not in printed report */}
      {symmetry && (
        <div style={{
          background: symmetry.level === 'red' ? '#3b0a0a' : '#2d1a00',
          borderBottom: `2px solid ${symmetry.level === 'red' ? '#ef4444' : '#f59e0b'}`,
          padding: '7px 16px',
          display: 'flex',
          alignItems: 'flex-start',
          gap: 10,
          flexShrink: 0,
        }}>
          <span style={{
            fontSize: 14, fontWeight: 700,
            color: symmetry.level === 'red' ? '#ef4444' : '#f59e0b',
            flexShrink: 0,
            marginTop: 1,
          }}>
            {symmetry.level === 'red' ? '🔴' : '🟠'} ROI CHECK REQUIRED
          </span>
          <div style={{ fontSize: 11, color: '#e5c07b', lineHeight: 1.5 }}>
            <strong>Abnormal L/R asymmetry detected:</strong> {symmetry.items.join(' · ')}.{' '}
            This may reflect incorrect ROI placement rather than a true clinical finding.{' '}
            <strong>Action:</strong> Re-analyse the scan in GE Lunar, verify L/R regions are correctly positioned,
            export XPS, then re-fetch in Labit to regenerate the report.
          </div>
        </div>
      )}

      {/* Report iframe */}
      <iframe
        key={renderUrl}
        src={renderUrl}
        style={{ flex: 1, border: 'none', width: '100%' }}
        title="DEXA Report"
      />
    </div>
  )
}
