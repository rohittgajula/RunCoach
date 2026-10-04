/** Big kcal ring: eaten / target, remaining in the centre. */
export function KcalRing({ eaten, target, size = 148 }: { eaten: number; target: number; size?: number }) {
  const stroke = 12
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const ratio = target > 0 ? Math.min(eaten / target, 1) : 0
  const remaining = Math.round(target - eaten)
  const over = remaining < 0
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle className="ring-track" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} fill="none" />
        <circle
          className={`ring-fill ${over ? 'is-over' : ''}`}
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - ratio)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="ring-centre">
        <span className="ring-value">{Math.round(eaten)}</span>
        <span className="ring-sub">of {Math.round(target)} kcal</span>
        <span className={`ring-left ${over ? 'bad' : ''}`}>
          {over ? `${-remaining} over` : `${remaining} left`}
        </span>
      </div>
    </div>
  )
}
