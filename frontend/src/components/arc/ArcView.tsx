/**
 * The Plan tab's first answer: where this is going, and where it came from.
 *
 * Every other screen in the app answers "what do I do now". That question gets
 * answered five times over and the one it leaves out is whether any of it is
 * working — which cannot be answered by a single day, or by a month of future
 * dates with nothing behind them. It needs both halves at once.
 *
 * Three parts, in the order the question gets asked: how far along am I, what
 * does the whole shape look like, and then week by week what actually happened.
 */

import { duration, dur, monthDay } from '../../lib/format'
import { Loading } from '../States'
import type { ArcWeek, TrainingArc } from '../../lib/types'
import { BlockChart, VolumeChart } from './ArcChart'
import { ArcProgress } from './ArcProgress'

const pct = (value: number, of: number) => (of > 0 ? Math.min(100, (value / of) * 100) : 0)

function Standing({ arc }: { arc: TrainingArc }) {
  const best = arc.weeks.length ? arc.weeks[arc.weeks.length - 1].best_run_s : 0
  const target = arc.goal.target_s ?? 0
  const recent = [...arc.weeks].reverse().find((w) => (w.past || w.current) && w.done.longest_run_s > 0)
  const now = recent?.done.longest_run_s ?? 0
  // Below your own record is the normal state after time off, and it is the one
  // thing a progress bar built only on "best ever" would hide completely.
  const regaining = best > 0 && now > 0 && now < best * 0.95

  return (
    <section className="card arc-standing">
      <p className="arc-standing-lab">Longest unbroken run</p>
      <p className="arc-standing-big num">
        {best > 0 ? duration(best) : '—'}
        {target > 0 && <span className="arc-standing-of"> of {duration(target)}</span>}
      </p>

      {target > 0 && (
        <div className="arc-meter" role="img"
          aria-label={`${duration(best)} of a ${duration(target)} target`}>
          <i className="arc-meter-fill" style={{ width: `${pct(best, target)}%` }} />
          {regaining && (
            <i className="arc-meter-now" style={{ left: `${pct(now, target)}%` }}
              aria-hidden="true" />
          )}
        </div>
      )}

      <p className="arc-standing-sub muted small">
        {arc.goal.kind === 'race'
          ? <>Target: {arc.goal.label}{arc.goal.date ? ` on ${monthDay(arc.goal.date)}` : ''}</>
          : <>Next milestone: {arc.goal.label}
              {arc.goal.rung ? ` · rung ${arc.goal.rung} of ${arc.goal.rungs}` : ''}</>}
      </p>
      {regaining && (
        <p className="arc-standing-note">
          Your last run held {duration(now)}. That is below your own best, so the plan is
          getting it back rather than pushing past it.
        </p>
      )}
    </section>
  )
}

/** The last four finished weeks, against the four before them.
 *
 *  Four because it is long enough that one missed Tuesday does not swing it and
 *  short enough to still be about now. Every figure is running only — the
 *  walking is already out, which is why these numbers are lower than the
 *  watch's and why they are the ones worth comparing. */
function Totals({ weeks }: { weeks: ArcWeek[] }) {
  const settled = weeks.filter((w) => w.past || w.current)
  if (settled.length < 2) return null
  const recent = settled.slice(-4)
  const before = settled.slice(-8, -4)

  const sum = (rows: ArcWeek[], pick: (w: ArcWeek) => number) =>
    rows.reduce((total, w) => total + pick(w), 0)

  const stats = [
    {
      key: 'distance',
      label: 'Distance run',
      value: `${(sum(recent, (w) => w.done.run_m) / 1000).toFixed(1)} km`,
      prev: before.length ? sum(before, (w) => w.done.run_m) : null,
      now: sum(recent, (w) => w.done.run_m),
    },
    {
      key: 'time',
      label: 'Time running',
      value: dur(sum(recent, (w) => w.done.run_s)),
      prev: before.length ? sum(before, (w) => w.done.run_s) : null,
      now: sum(recent, (w) => w.done.run_s),
    },
    {
      key: 'runs',
      label: 'Runs',
      value: String(sum(recent, (w) => w.done.runs)),
      prev: before.length ? sum(before, (w) => w.done.runs) : null,
      now: sum(recent, (w) => w.done.runs),
    },
    {
      key: 'gym',
      label: 'Gym sessions',
      value: String(sum(recent, (w) => w.done.gym)),
      prev: before.length ? sum(before, (w) => w.done.gym) : null,
      now: sum(recent, (w) => w.done.gym),
    },
  ]

  return (
    <section className="card arc-card">
      <h2 className="arc-h">Last four weeks</h2>
      <div className="arc-tiles">
        {stats.map((s) => {
          const delta = s.prev != null && s.prev > 0
            ? Math.round(((s.now - s.prev) / s.prev) * 100)
            : null
          return (
            <div className="arc-tile" key={s.key}>
              <span className="arc-tile-label">{s.label}</span>
              <span className="arc-tile-value num">{s.value}</span>
              {delta != null && delta !== 0 && (
                <span className={`arc-tile-delta ${delta > 0 ? 'is-up' : 'is-down'}`}>
                  {delta > 0 ? '+' : ''}{delta}% vs the four before
                </span>
              )}
              {delta === 0 && <span className="arc-tile-delta">level</span>}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function WeekRow({ week, peakRunS }: { week: ArcWeek; peakRunS: number }) {
  const settled = week.past || week.current
  const doneW = pct(week.done.run_s, peakRunS)
  const planW = pct(week.planned.run_s, peakRunS)
  const nothing = settled && !week.done.runs && !week.done.gym && !week.planned.runs

  return (
    <li className={`arc-week ${week.current ? 'is-now' : ''} ${week.past ? 'is-past' : 'is-ahead'}`}>
      <div className="arc-week-when">
        <b>{monthDay(week.start)}</b>
        <span className="muted">{week.current ? 'this week' : week.past ? 'done' : 'ahead'}</span>
      </div>

      <div className="arc-week-track" aria-hidden="true">
        {planW > 0 && <i className="arc-week-plan" style={{ width: `${planW}%` }} />}
        {doneW > 0 && <i className="arc-week-done" style={{ width: `${doneW}%` }} />}
      </div>

      <div className="arc-week-figs">
        {nothing ? (
          <span className="arc-week-empty">nothing recorded</span>
        ) : (
          <>
            <span className="num">
              {settled && week.done.run_s > 0 ? dur(week.done.run_s) : dur(week.planned.run_s)}
            </span>
            {(settled ? week.done.longest_run_s : week.planned.block_s) > 0 && (
              <span className="arc-week-block num">
                {duration(settled ? week.done.longest_run_s : week.planned.block_s)} block
              </span>
            )}
            {(settled ? week.done.gym : week.planned.gym) > 0 && (
              <span className="arc-week-gym">
                {settled ? week.done.gym : week.planned.gym} gym
              </span>
            )}
            {week.missed > 0 && <span className="arc-week-missed">{week.missed} missed</span>}
          </>
        )}
      </div>
    </li>
  )
}

export function ArcView({
  arc, loading, error,
}: { arc?: TrainingArc; loading: boolean; error: unknown }) {
  if (loading) return <div className="arc-loading"><Loading block /></div>
  if (error || !arc) {
    return (
      <section className="card">
        <p className="banner-title">Could not load the arc</p>
        <p className="muted small">Pull down to try again.</p>
      </section>
    )
  }
  if (!arc.weeks.length) {
    return (
      <section className="card">
        <p className="banner-title">Nothing to draw yet</p>
        <p className="muted small">
          One run or one planned week is enough to start this. It fills in from your
          Garmin history as soon as there is any.
        </p>
      </section>
    )
  }

  const best = arc.weeks[arc.weeks.length - 1].best_run_s
  // Newest first on the past side reads better than a scroll back through
  // October: what you did last week is what you want to see first.
  const past = arc.weeks.filter((w) => w.past).slice().reverse()
  const ahead = arc.weeks.filter((w) => !w.past)

  return (
    <div className="arc">
      <Standing arc={arc} />

      <Totals weeks={arc.weeks} />

      <section className="card arc-card">
        <BlockChart weeks={arc.weeks} bestS={best} />
      </section>

      <section className="card arc-card">
        <VolumeChart weeks={arc.weeks} />
        {arc.notes.length > 0 && (
          <ul className="arc-notes">
            {arc.notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        )}
      </section>

      <ArcProgress />

      <section className="card arc-card">
        <h2 className="arc-h">Ahead</h2>
        <ul className="arc-weeks">
          {ahead.map((w) => <WeekRow key={w.start} week={w} peakRunS={arc.peak.run_s} />)}
        </ul>
      </section>

      <section className="card arc-card">
        <h2 className="arc-h">Behind</h2>
        <ul className="arc-weeks">
          {past.map((w) => <WeekRow key={w.start} week={w} peakRunS={arc.peak.run_s} />)}
        </ul>
      </section>
    </div>
  )
}
