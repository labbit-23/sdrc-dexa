'use client'

import { useState } from 'react'

export default function ReportBrowserPage({
  params,
}: {
  params: { patientId: string }
}) {
  const { patientId } = params
  const [dark, setDark] = useState(true)
  const [letterhead, setLetterhead] = useState(false)
  const [fatMode, setFatMode] = useState(false)

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
        <div style={{ fontSize: 12, color: '#9E9E9E' }}>
          <span style={{ color: '#14a8ae', fontWeight: 700 }}>SDRC</span>
          {' '}· DEXA Report · Patient {patientId}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Athletic / Fat Analysis toggle */}
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
          {/* Dark / Light toggle */}
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
            {dark && !letterhead ? '☀ Light mode' : '🌙 Dark mode'}
          </button>
          {/* Letterhead preview */}
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
            {letterhead ? '✕ Exit letterhead' : '📄 Print on letterhead'}
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
            Open in new tab
          </a>
          {btn(`/api/bmd/pdf?patient=${patientId}${modeParam}`, '↓ PDF (Print)', { background: '#0D7377', color: '#fff' })}
          {btn(`/api/bmd/pdf-dark?patient=${patientId}${modeParam}`, '↓ PDF (Dark)', { background: '#1a3a55', color: '#00BCD4' })}
          {btn(`/api/bmd/pdf-letterhead?patient=${patientId}${modeParam}`, '↓ PDF (Letterhead)', { background: '#92400e', color: '#fef3c7' })}
        </div>
      </div>

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
