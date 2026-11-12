import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { dur, parseDate } from '../../lib/format'
import { errorText, fetchCalendarDay, useCalendarMonth } from '../../lib/queries'
import type { ActivityCard, CalDay, MonthDay, Workout } from '../../lib/types'
import { ChevronLeft, ChevronRight } from '../Icons'
import { ErrorState } from '../States'
import { DaySheet } from './DaySheet'
import { LEGEND, STATUS_TEXT, monthCells, monthLabel, monthOf, shiftMonth } from './monthUtil'

const DOW = ['M', 'T', 'W', 'T', 'F', 'S', 'S']

const RUN_SPORTS = new Set(['running', 'walking', 'hiking', 'trail_running', 'treadmill_running'])

/** Short enough for a 45px cell. "Run/walk" does not fit; "R/W" means nothing. */
const KIND_SHORT: Record<string, string> = {
  EASY: 'Easy', LONG: 'Long', RUN_WALK: 'Easy', INTERVALS: 'Reps',
  TEMPO: 'Tempo', RACE: 'Race', WALK: 'Walk', REST: 'Rest', STRENGTH: 'Gym',
}

const mins = (seconds: number) => `${Math.max(1, Math.round(seconds / 60))}m`

/**
 * The two lines under the date.
 *
 * A dot told you a day had *something* and nothing more, so the month was a
 * wall of dots you had to tap one at a time to read. Every figure below was
 * already in the response the grid was given.
 *
 * What a day shows depends on whether it has happened. For a run already done
 * the distance is the fact worth seeing — it is what you actually covered, and
 * comparing it against the plan is the whole point of looking. For one still
 * ahead the duration is the fact worth seeing, because that is what you have to
 * find time for.
 */
function cellLines(cell: MonthDay): { kind: string; value: string; gymOnly?: boolean } | null {
  const done = cell.activities.find((a) => RUN_SPORTS.has(a.sport)) ?? cell.activities[0]
  if (done) {
    const km = (done.distance_m ?? 0) / 1000
    return {
      kind: cell.planned ? (KIND_SHORT[cell.planned.kind] ?? 'Run') : 'Run',
      value: km >= 0.1 ? `${km.toFixed(km < 10 ? 1 : 0)}k` : mins(done.duration_s),
    }
  }
  if (cell.planned) {
    return {
      kind: KIND_SHORT[cell.planned.kind] ?? cell.planned.kind.toLowerCase(),
      value: mins(cell.planned.duration_s),
    }
  }
  // A gym day with no run on it was falling through to the generic status dot,
  // so the one kind of day the strength plan adds looked like a day with
  // nothing on it. The bar beneath marks "there is ALSO a gym session"; on a
  // day that is only gym, the cell has to say so itself.
  if (cell.strength) {
    return {
      kind: 'Gym',
      value: cell.strength.duration_s ? mins(cell.strength.duration_s) : '·',
      gymOnly: true,
    }
  }
  return null
}

type Handlers = {
  onWorkout: (w: Workout) => void
  onActivity: (a: ActivityCard) => void
  onGuide: (w: Workout) => void
  onReview: (a: ActivityCard) => void
}

export function MonthView({ today, ...handlers }: { today: string } & Handlers) {
  const client = useQueryClient()
  const [month, setMonth] = useState(monthOf(today))
  const [openDay, setOpenDay] = useState<CalDay | null>(null)
  const [loadingDate, setLoadingDate] = useState<string | null>(null)
  const [tapError, setTapError] = useState('')
  const query = useCalendarMonth(month)
  // While the next month loads, keep the grid shape but drop the old month's marks.
  const data = query.isPlaceholderData ? undefined : query.data
  const cells = monthCells(month, data?.days)
  const now = query.data?.today ?? today

  const open = async (day: MonthDay) => {
    setTapError('')
    setLoadingDate(day.date)
    try {
      const response = await fetchCalendarDay(client, day.date)
      const full = response.days.find((d) => d.date === day.date)
      if (!full || !full.items.length) return
      if (full.items.length === 1) {
        const item = full.items[0]
        if (item.type === 'workout') handlers.onWorkout(item.workout)
        else if (item.type === 'activity') handlers.onActivity(item.activity)
        else setOpenDay(full)
      } else {
        setOpenDay(full)
      }
    } catch (error) {
      setTapError(errorText(error, 'Could not open that day.'))
    } finally {
      setLoadingDate(null)
    }
  }

  const totals = data?.totals ?? null

  return (
    <section className="card month">
      <div className="month-nav">
        <button type="button" className="icon-btn" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>
          <ChevronLeft />
        </button>
        <button type="button" className="month-label" onClick={() => setMonth(monthOf(today))} title="Back to this month">
          {monthLabel(month)}
        </button>
        <button type="button" className="icon-btn" aria-label="Next month" onClick={() => setMonth(shiftMonth(month, 1))}>
          <ChevronRight />
        </button>
      </div>

      <div className="month-grid" role="grid" aria-busy={query.isFetching}>
        {DOW.map((d, i) => <span key={i} className="month-dow">{d}</span>)}
        {cells.map((cell, i) => {
          if (!cell) return <span key={`x${i}`} className="month-cell is-blank" />
          const tappable = !!cell.planned || cell.activities.length > 0
          const status = cell.status === 'today' ? (cell.planned ? 'planned' : null) : cell.status
          const lines = cellLines(cell)
          const label = [
            parseDate(cell.date).toLocaleDateString(undefined, { day: 'numeric', month: 'long' }),
            cell.planned?.title,
            status ? STATUS_TEXT[status] : null,
          ].filter(Boolean).join(', ')
          return (
            <button
              key={cell.date}
              type="button"
              className={`month-cell ${cell.date === now ? 'is-today' : ''} ${cell.date < now ? 'is-past' : ''} ${loadingDate === cell.date ? 'is-loading' : ''} ${cell.planned?.kind === 'RACE' ? 'is-race' : ''}`}
              disabled={!tappable}
              aria-label={label}
              onClick={() => open(cell)}
            >
              <span className="month-num">{parseDate(cell.date).getDate()}</span>
              {lines ? (
                <span className={`month-lines ${lines.gymOnly ? 'is-gym' : ''}`}>
                  <span className="month-kind">{lines.kind}</span>
                  <span className="month-value">{lines.value}</span>
                </span>
              ) : (
                <span className={`month-mark ${status && status !== 'rest' ? `is-${status}` : ''}`} />
              )}
              {cell.strength && !lines?.gymOnly && (
                <span className="month-gym" title="Also a strength session">Gym</span>
              )}
            </button>
          )
        })}
      </div>

      {query.isError && !query.data && <ErrorState message={errorText(query.error, 'The month did not load.')} onRetry={() => query.refetch()} />}
      {tapError && <p className="bad small centered-text">{tapError}</p>}

      <div className="month-legend">
        {LEGEND.map(({ status, label }) => (
          <span key={status}><i className={`month-mark is-${status}`} /> {label}</span>
        ))}
      </div>

      {totals && (
        <p className="month-totals">
          <strong>{totals.runs_done} of {totals.runs_planned} runs</strong> · {dur(totals.actual_s)}
          {totals.runs_missed > 0 && <span className="bad"> · {totals.runs_missed} missed</span>}
        </p>
      )}

      <DaySheet day={openDay} onClose={() => setOpenDay(null)} {...handlers} />
    </section>
  )
}
