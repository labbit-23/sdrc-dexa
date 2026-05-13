'use client'

interface Props {
  label: string
  t: number | null
  bmd?: number | null
}

const T_MIN = -4, T_MAX = 3

export default function TScoreBar({ label, t, bmd }: Props) {
  const pct = t !== null
    ? Math.max(0, Math.min(100, ((t - T_MIN) / (T_MAX - T_MIN)) * 100))
    : null

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-gray-500 w-36 flex-shrink-0">{label}</span>
      <div className="relative flex-1 h-5 rounded-full overflow-hidden bg-gray-100 flex">
        {/* Colour bands */}
        <div className="h-full" style={{ width: `${((-2.5 - T_MIN) / (T_MAX - T_MIN)) * 100}%`, backgroundColor: '#fca5a5' }} />
        <div className="h-full" style={{ width: `${(1.5 / (T_MAX - T_MIN)) * 100}%`, backgroundColor: '#fde68a' }} />
        <div className="h-full flex-1" style={{ backgroundColor: '#bbf7d0' }} />
        {/* Marker */}
        {pct !== null && (
          <div
            className="absolute top-0 bottom-0 w-1 bg-gray-800 rounded"
            style={{ left: `calc(${pct}% - 2px)` }}
          />
        )}
      </div>
      <div className="w-24 text-right">
        {t !== null ? (
          <span className="text-sm font-bold text-gray-800">
            {t >= 0 ? '+' : ''}{t.toFixed(1)}
          </span>
        ) : (
          <span className="text-sm text-gray-400">—</span>
        )}
        {bmd !== null && bmd !== undefined && (
          <span className="ml-1 text-xs text-gray-400">{bmd.toFixed(3)}</span>
        )}
      </div>
    </div>
  )
}
