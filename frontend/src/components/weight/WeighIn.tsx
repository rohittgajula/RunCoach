/**
 * Today's weigh-in: one number, one tap.
 *
 * Weight logging has existed since the profile was built — a full history, a
 * chart, a trend, mirrored onto the athlete so the fuelling maths reads one
 * row. All of it three taps deep in Me → Profile, which is the right place for
 * the history and the wrong place for the daily act. Rohit weighs himself most
 * mornings; an entry that takes three taps to reach is an entry that does not
 * get made.
 *
 * So this is the entry and nothing else: today's number, a field, a button.
 * The chart, the trend and the deleting all stay where they were, and the
 * "See the trend" link goes there rather than this screen growing a second
 * copy of them.
 *
 * Shows today's reading once it exists rather than hiding, because the useful
 * thing after weighing in is seeing what you weighed.
 */

import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { errorText, useAddMetric, useMetricEntries } from '../../lib/queries'

/** Narrow enough to reject a typo'd 7.2 or 720, wide enough for any adult. */
const MIN_KG = 25
const MAX_KG = 300

export function WeighIn() {
  const [text, setText] = useState('')
  const entries = useMetricEntries('weight', '3m')
  const add = useAddMetric()

  const latest = entries.data?.current
  const today = new Date().toISOString().slice(0, 10)
  const loggedToday = latest?.recorded_at?.slice(0, 10) === today

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const value = Number(text.replace(',', '.'))
    if (!Number.isFinite(value) || value < MIN_KG || value > MAX_KG) return
    add.mutate(
      { kind: 'weight', value, recorded_at: new Date().toISOString() },
      { onSuccess: () => setText('') },
    )
  }

  const value = Number(text.replace(',', '.'))
  const ready = Number.isFinite(value) && value >= MIN_KG && value <= MAX_KG

  return (
    <section className="card stack weighin">
      <div className="row">
        <strong>Weight</strong>
        {/* The history, chart and trend already live in the profile sheet.
            This card is the daily act; that is the record. */}
        <Link to="/me?metric=weight" className="small muted weighin-more">See the trend</Link>
      </div>

      {loggedToday ? (
        <p className="weighin-today">
          <b className="num">{latest!.value}</b> kg today
          <span className="muted small"> · logged</span>
        </p>
      ) : (
        <form className="weighin-form" onSubmit={submit}>
          <input
            type="number"
            inputMode="decimal"
            step="0.1"
            min={MIN_KG}
            max={MAX_KG}
            value={text}
            placeholder={latest ? String(latest.value) : 'kg'}
            onChange={(e) => setText(e.target.value)}
            aria-label="Today's weight in kilograms"
          />
          <button type="submit" className="btn btn-primary" disabled={!ready || add.isPending}>
            {add.isPending ? 'Saving…' : 'Log'}
          </button>
        </form>
      )}

      {add.error && (
        <p className="small bad" role="alert">{errorText(add.error, 'Not saved.')}</p>
      )}
    </section>
  )
}
