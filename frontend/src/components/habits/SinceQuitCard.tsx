import { parseDate } from '../../lib/format'
import type { HabitSummary } from '../../lib/types'
import { CheckIcon } from '../Icons'

const rupees = (v: number) => `₹${Math.round(v).toLocaleString('en-IN')}`

const whenText = (at: string | null) => {
  if (!at) return ''
  const d = at.length > 10 ? new Date(at) : parseDate(at)
  const year = d.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year })
}

/** Days, cigarettes avoided, money saved, and the public-health timeline ("typically"). */
export function SinceQuit({ smoke }: { smoke: HabitSummary['smoke'] }) {
  const since = smoke.since_quit
  if (!since) return null
  return (
    <div className="since-quit">
      <h3 className="habit-sub">Since you quit</h3>
      <dl className="kv kv-row kv-row-3">
        <div><dt>Days</dt><dd>{since.days}</dd></div>
        <div><dt>Not smoked</dt><dd>{since.cigarettes_avoided != null ? Math.round(since.cigarettes_avoided) : '--'}</dd></div>
        <div><dt>Saved</dt><dd>{since.money_saved != null ? rupees(since.money_saved) : '--'}</dd></div>
      </dl>
      {since.cigarettes_avoided == null && <p className="muted small">Add your usual cigarettes per day in Settings to see what you’ve avoided.</p>}
      {since.money_saved == null && since.cigarettes_avoided != null && <p className="muted small">Add the price per cigarette in Settings to see money saved.</p>}
      {smoke.milestones.length > 0 && (
        <>
          <p className="muted small">What typically happens in the body after quitting:</p>
          <ul className="milestones">
            {smoke.milestones.map((m) => (
              <li key={m.label} className={`milestone ${m.reached ? 'is-reached' : ''}`}>
                <span className="milestone-mark" aria-hidden="true">{m.reached ? <CheckIcon size={14} /> : null}</span>
                <span className="grow">{m.label}</span>
                {!m.reached && <span className="muted small">{whenText(m.at)}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
