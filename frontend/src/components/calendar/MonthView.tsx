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
        else handlers.onActivity(item.activity)
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
          const label = [
            parseDate(cell.date).toLocaleDateString(undefined, { day: 'numeric', month: 'long' }),
            cell.planned?.title,
            status ? STATUS_TEXT[status] : null,
          ].filter(Boolean).join(', ')
          return (
            <button
              key={cell.date}
              type="button"
              className={`month-cell ${cell.date === now ? 'is-today' : ''} ${cell.date < now ? 'is-past' : ''} ${loadingDate === cell.date ? 'is-loading' : ''}`}
              disabled={!tappable}
              aria-label={label}
              onClick={() => open(cell)}
            >
              <span className="month-num">{parseDate(cell.date).getDate()}</span>
              <span className={`month-mark ${status && status !== 'rest' ? `is-${status}` : ''}`} />
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
