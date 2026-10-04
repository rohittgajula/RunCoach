import { useState } from 'react'
import type { CheckinEntry } from '../../lib/types'
import { cap, rpeLabel } from './checkinUtil'
import { CheckinForm } from './CheckinForm'

/** Activity sheet: the check-in summary, or "Add check-in" (inline form, no nested sheet). */
export function CheckinSection({
  activityId, entry, journalled,
}: { activityId: number; entry: CheckinEntry | null | undefined; journalled: boolean }) {
  const [adding, setAdding] = useState(false)
  const [saved, setSaved] = useState<CheckinEntry | null>(null)
  const shown = saved ?? entry ?? null

  return (
    <section className="detail-section">
      <h3>Check-in</h3>
      {shown ? (
        <CheckinSummary entry={shown} />
      ) : journalled ? (
        <p className="muted">Logged in your journal.</p>
      ) : adding ? (
        <div className="card ci-inline">
          <CheckinForm
            activityId={activityId}
            onDone={(e) => { setSaved(e); setAdding(false) }}
            onCancel={() => setAdding(false)}
          />
        </div>
      ) : (
        <button type="button" className="btn btn-secondary btn-block" onClick={() => setAdding(true)}>
          Add check-in
        </button>
      )}
    </section>
  )
}

function CheckinSummary({ entry }: { entry: CheckinEntry }) {
  const x = entry.extracted ?? {}
  const rpe = entry.rpe ?? (typeof x.rpe === 'number' ? x.rpe : null)
  const legs = entry.legs ?? x.legs
  const breathing = entry.breathing ?? x.breathing
  const pain = entry.pain ?? x.pain ?? null
  // `text` is the server's one-line summary of these same fields, not the athlete's note.
  const note = entry.note || (typeof x.note === 'string' ? x.note : '')
  if (x.skipped) return <p className="muted">Skipped{x.reason && x.reason !== 'skipped' ? ` — ${x.reason}` : ''}.</p>
  return (
    <div className="card ci-summary">
      {rpe != null && (
        <p className="ci-summary-rpe"><b>{rpe}/10</b> <span className="muted">· {rpeLabel(rpe)}</span></p>
      )}
      <div className="detail-tags">
        {legs && <span className="tag">Legs {legs}</span>}
        {breathing && <span className="tag">Breathing {breathing}</span>}
        {pain ? (
          <span className="tag tag-bad">{cap(pain.where)} pain {pain.level}/10</span>
        ) : entry.pain_reported ? (
          <span className="tag tag-bad">Pain reported</span>
        ) : (
          <span className="tag tag-ok">No pain</span>
        )}
      </div>
      {note && <p className="ci-summary-note">“{note}”</p>}
    </div>
  )
}
