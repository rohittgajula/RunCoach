import type { SignalReason, Verdict } from '../../lib/types'
import { VERDICT, signalName, signalValue } from './checkinUtil'

export function VerdictPill({ verdict }: { verdict: Verdict }) {
  const v = VERDICT[verdict] ?? VERDICT.no_plan
  return <span className={`verdict-pill verdict-${v.tone}`}>{v.word}</span>
}

/** "Sleep 6h 10m · watch" chips, worst first, at most `max`. */
export function SignalChips({ reasons, max = 5 }: { reasons: SignalReason[]; max?: number }) {
  const rank = { bad: 0, watch: 1, good: 2 } as const
  const shown = [...reasons].sort((a, b) => (rank[a.status] ?? 3) - (rank[b.status] ?? 3)).slice(0, max)
  if (!shown.length) return null
  return (
    <ul className="signal-chips">
      {shown.map((r) => {
        // The server's `label` already carries the value ("Sleep 6h 10m").
        const value = r.label ? '' : signalValue(r)
        return (
          <li key={r.signal} className={`signal-chip is-${r.status}`} title={r.baseline != null ? `Your usual: ${r.baseline}` : undefined}>
            <i aria-hidden="true" />
            <span>
              {r.label || signalName(r.signal)}
              {value && <b> {value}</b>}
            </span>
            <span className="signal-status">{r.status}</span>
          </li>
        )
      })}
    </ul>
  )
}
