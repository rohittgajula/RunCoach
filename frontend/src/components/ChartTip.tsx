import type { ReactNode } from 'react'

type Item = { value?: unknown; name?: unknown; dataKey?: unknown; color?: string; payload?: unknown }
type TipProps = { active?: boolean; label?: unknown; payload?: ReadonlyArray<Item> }
export type TipLine = { text: ReactNode; color?: string }

/**
 * The app's chart tooltip: small rounded card, soft shadow, no border. Charts pass
 * `{...TIP}` so it sits at the top of the plot (above bars/points, clamped inside).
 */
export function chartTip(render: (items: ReadonlyArray<Item>, label: string) => { title?: ReactNode; lines: TipLine[] } | null) {
  return function ChartTipContent({ active, payload, label }: TipProps) {
    if (!active || !payload?.length) return null
    const out = render(payload, label == null ? '' : String(label))
    if (!out || !out.lines.length) return null
    return (
      <div className="chart-tip">
        {out.title && <p className="chart-tip-title">{out.title}</p>}
        {out.lines.map((l, i) => (
          <p key={i} className="chart-tip-line">
            {l.color && <i style={{ background: l.color }} />}
            {l.text}
          </p>
        ))}
      </div>
    )
  }
}

/** Tooltip placement shared by every chart. */
export const TIP = {
  position: { y: 0 },
  offset: 12,
  allowEscapeViewBox: { x: false, y: false },
  isAnimationActive: false,
  wrapperStyle: { outline: 'none', zIndex: 5, pointerEvents: 'none' as const },
}

export const num = (v: unknown) => (typeof v === 'number' ? v : Number(v))
