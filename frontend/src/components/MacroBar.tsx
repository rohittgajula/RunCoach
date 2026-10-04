/** One macro: label, eaten / target g, a bar that turns amber past 110 %. */
export function MacroBar({
  label, eaten, target, unit = 'g', tone,
}: { label: string; eaten: number; target: number; unit?: string; tone: 'carbs' | 'protein' | 'fat' }) {
  const ratio = target > 0 ? eaten / target : 0
  return (
    <div className="macro">
      <div className="macro-head">
        <span className="macro-label">{label}</span>
        <span className="macro-value">
          <strong>{Math.round(eaten)}</strong>
          <span className="muted"> / {Math.round(target)} {unit}</span>
        </span>
      </div>
      <div className="macro-track" role="meter" aria-valuenow={Math.round(eaten)} aria-valuemax={Math.round(target)} aria-label={label}>
        <div
          className={`macro-fill macro-${tone} ${ratio > 1.1 ? 'is-over' : ''}`}
          style={{ width: `${Math.min(100, ratio * 100)}%` }}
        />
      </div>
    </div>
  )
}
