import { useId } from 'react'

/** Tiny SVG trend for the profile cards — no axes, no library. */
export function Sparkline({
  values, area = false, color = '#1f7ae0', height = 64,
}: { values: number[]; area?: boolean; color?: string; height?: number }) {
  const gradient = useId().replace(/:/g, '')
  const clean = values.filter((v) => Number.isFinite(v))
  if (clean.length < 2) return <div className="spark-empty" style={{ height }} />
  const width = 100
  const min = Math.min(...clean)
  const max = Math.max(...clean)
  const span = max - min || 1
  const points = clean.map((v, i) => [
    (i / (clean.length - 1)) * width,
    height - 4 - ((v - min) / span) * (height - 8),
  ])
  const line = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ')
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ height }} aria-hidden="true">
      {area && (
        <>
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.3} />
              <stop offset="100%" stopColor={color} stopOpacity={0.03} />
            </linearGradient>
          </defs>
          <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#${gradient})`} />
        </>
      )}
      <path d={line} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
