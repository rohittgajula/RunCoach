/** 0–100 ring (compliance, readiness). Green ≥ 80, amber ≥ 60, red below. */
export function ScoreRing({
  score, size = 88, label, stroke = 9,
}: { score: number | null; size?: number; label?: string; stroke?: number }) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const value = score == null ? 0 : Math.max(0, Math.min(100, score))
  const tone = score == null ? '' : value >= 80 ? 'is-hit' : value >= 60 ? 'is-close' : 'is-missed'
  return (
    <div className="ring score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle className="ring-track" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} fill="none" />
        {score != null && (
          <circle
            className={`score-ring-fill ${tone}`}
            cx={size / 2}
            cy={size / 2}
            r={r}
            strokeWidth={stroke}
            fill="none"
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={c * (1 - value / 100)}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        )}
      </svg>
      <div className="ring-centre">
        <span className="score-ring-value" style={{ fontSize: Math.round(size * 0.3) }}>
          {score == null ? '--' : Math.round(value)}
        </span>
        {label && <span className="ring-sub">{label}</span>}
      </div>
    </div>
  )
}
