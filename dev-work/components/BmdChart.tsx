'use client'

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import { Scan, BmdResult } from '../lib/supabase'
import { formatDate } from '../lib/supabase'

interface Props {
  scans: (Scan & { bmd_results: BmdResult[] })[]
}

const SITE_COLORS: Record<string, string> = {
  'L1-L4': '#0D7377',
  'Neck-left': '#166534',
  'Total-left': '#14532d',
  'Neck-right': '#92400e',
  'Total-right': '#78350f',
}

export default function BmdChart({ scans }: Props) {
  // Build chart data: one point per scan, columns per site+side combo
  const sortedScans = [...scans].sort((a, b) =>
    (a.scan_date ?? '').localeCompare(b.scan_date ?? '')
  )

  const chartData = sortedScans.map(s => {
    const point: Record<string, string | number | null> = {
      date: formatDate(s.scan_date),
    }
    for (const r of s.bmd_results) {
      const key = r.side ? `${r.site}-${r.side}` : r.site
      point[key] = r.bmd
    }
    return point
  })

  const seriesKeys = Object.keys(SITE_COLORS).filter(k =>
    chartData.some(d => d[k] !== undefined)
  )

  if (seriesKeys.length === 0) return null

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} />
        <YAxis
          domain={['auto', 'auto']}
          tick={{ fontSize: 11 }}
          label={{ value: 'BMD g/cm²', angle: -90, position: 'insideLeft', fontSize: 11 }}
        />
        <Tooltip formatter={(v: number) => v.toFixed(3)} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {seriesKeys.map(k => (
          <Line
            key={k}
            type="monotone"
            dataKey={k}
            stroke={SITE_COLORS[k]}
            strokeWidth={2}
            dot={{ r: 4 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
