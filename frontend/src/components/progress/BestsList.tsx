import { parseDate } from '../../lib/format'
import type { ProgressBest } from '../../lib/types'
import { fmtValue } from './progressUtil'

const short = (iso: string | null) =>
  iso ? parseDate(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' }) : ''

export function BestsList({ bests }: { bests: ProgressBest[] }) {
  if (!bests.length) return null
  return (
    <ul className="bests">
      {bests.map((b) => (
        <li key={b.key} className={`best ${b.is_new ? 'is-new' : ''}`}>
          <span className="grow">{b.label}</span>
          {b.is_new && <span className="tag tag-ok">New best</span>}
          <span className="best-value">{fmtValue(b.value, b.unit)}</span>
          <span className="muted small best-date">{short(b.date)}</span>
        </li>
      ))}
    </ul>
  )
}
