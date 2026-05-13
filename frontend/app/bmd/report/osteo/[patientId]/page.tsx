'use client'

import { useState } from 'react'

export default function OsteoReportPage({
  params,
}: {
  params: { patientId: string }
}) {
  const { patientId } = params
  const [letterhead, setLetterhead] = useState(false)

  const renderUrl = letterhead
    ? `/bmd/render/osteo/${patientId}?lh=1`
    : `/bmd/render/osteo/${patientId}`

  const btn = (href: string, label: string, style: React.CSSProperties) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        padding: '5px 14px', borderRadius: 5, fontSize: 12, fontWeight: 700,
        textDecoration: 'none', cursor: 'pointer', ...style,
      }}
    >
      {label}
    </a>
  )

  return (
    <div style={{ position: 'fixed', inset: 0, background: '#f0f4f8', display: 'flex', flexDirection: 'column' }}>
      {/* Toolbar */}
      <div style={{
        height: 44, background: '#ffffff', borderBottom: '1px solid #d0dce8',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 16px', flexShrink: 0,
      }}>
        <div style={{ fontSize: 12, color: '#6b7280' }}>
          <span style={{ color: '#0D7377', fontWeight: 700 }}>SDRC</span>
          {' '}· Bone Density Report · {patientId}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>

          {/* Letterhead toggle */}
          <button
            onClick={() => setLetterhead(l => !l)}
            style={{
              padding: '5px 14px', borderRadius: 5, fontSize: 12, fontWeight: 600,
              background: letterhead ? '#fff3e0' : '#f5f7fa',
              color: letterhead ? '#b45309' : '#374151',
              border: `1px solid ${letterhead ? '#f59e0b88' : '#d0dce8'}`,
              cursor: 'pointer',
            }}
          >
            {letterhead ? '✕ Exit letterhead' : '📄 Letterhead preview'}
          </button>

          {/* Open in new tab */}
          <a
            href={renderUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              padding: '5px 14px', borderRadius: 5, fontSize: 12, fontWeight: 600,
              background: '#f5f7fa', color: '#374151',
              border: '1px solid #d0dce8', textDecoration: 'none',
            }}
          >
            Open in new tab
          </a>

          {/* PDF downloads */}
          {btn(`/api/bmd/pdf-osteo?patient=${patientId}`, '↓ PDF', {
            background: '#0D7377', color: '#fff',
          })}
          {btn(`/api/bmd/pdf-osteo?patient=${patientId}&lh=1`, '↓ PDF (Letterhead)', {
            background: '#92400e', color: '#fef3c7',
          })}
        </div>
      </div>

      {/* Report iframe */}
      <iframe
        key={renderUrl}
        src={renderUrl}
        style={{ flex: 1, border: 'none', width: '100%' }}
        title="Bone Density Report"
      />
    </div>
  )
}
