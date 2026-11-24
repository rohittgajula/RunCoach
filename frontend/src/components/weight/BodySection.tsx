/**
 * Health → Weight: the history behind the one number on Today.
 *
 * Logging has existed since the profile was built — entries, a chart, a trend,
 * mirrored onto the athlete so the fuelling maths reads one row — and all of
 * it lived in a sheet three taps deep in Me. Rohit asked for the daily entry
 * on Today and the detail here, which is the right split: Today is where you
 * weigh yourself, this is where you see what it has been doing.
 *
 * Deliberately a thin wrapper over the sheet's own content rather than a
 * second implementation. There is exactly one place that knows how to add,
 * chart and delete a weight entry, and a prettier copy of it here would be a
 * second thing to keep correct and the one that drifted.
 */

import { useState } from 'react'
import { MetricSheet } from '../profile/MetricSheet'
import { WeighIn } from './WeighIn'

export function BodySection() {
  // Opened by default: arriving at a screen called Weight to find a button
  // that opens the weight is one tap of nothing.
  const [open, setOpen] = useState(true)

  return (
    <div className="stack">
      <WeighIn />
      <section className="card stack">
        <div className="row">
          <strong>History</strong>
          {!open && (
            <button type="button" className="btn btn-secondary btn-sm"
                    onClick={() => setOpen(true)}>Open</button>
          )}
        </div>
        <p className="muted small">
          Every weigh-in, with the trend. The number on Today writes here.
        </p>
      </section>
      <MetricSheet kind={open ? 'weight' : null} onClose={() => setOpen(false)} />
    </div>
  )
}
