/**
 * Food, on Today.
 *
 * It lives here because of when it is used rather than what it is. Logging a
 * meal happens three or four times a day and deciding whether to eat something
 * happens just before that — both of them while he is already looking at today,
 * not while he is reading a chart in Health. Health → More → Food was two taps
 * and a sideways scroll of the chip row away from the moment either question
 * gets asked, which is how a daily habit quietly becomes a weekly one.
 *
 * The card stays small until it is used. Closed, it is four numbers and two
 * buttons. "Before you eat it" opens the real pre-meal check in place — the same
 * component the Food page uses, in its chrome-less variant — rather than
 * navigating away, because the answer is only useful in the ten seconds before
 * the decision.
 *
 * The full page (trends, past days, water, fuelling) is still a tap away on the
 * title, which is where someone who wants to *look* at their eating will go.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, DietIcon, PlusIcon, SparkIcon } from '../Icons'
import { LogMealSheet } from '../LogMealSheet'
import { PreMealCheck } from '../diet/PreMealCheck'
import { Skeleton } from '../States'
import { todayISO } from '../../lib/format'
import { useDietDay } from '../../lib/queries'

export function TodayFood() {
  const date = todayISO()
  const day = useDietDay(date)
  const [logging, setLogging] = useState(false)
  const [checking, setChecking] = useState(false)
  const data = day.data?.date === date ? day.data : undefined

  // A failed request is not worth a card of its own on Today — the Food page
  // says so properly. Staying quiet beats an error box above the week's plan.
  if (day.isError && !data) return null

  const target = Math.round(data?.targets.kcal ?? 0)
  const eaten = Math.round(data?.eaten.kcal ?? 0)
  const left = target - eaten
  const pct = target > 0 ? Math.min(100, Math.round((eaten / target) * 100)) : 0
  const proteinShort = Math.max(0, Math.round((data?.targets.protein_g ?? 0) - (data?.eaten.protein_g ?? 0)))

  return (
    <section className="card stack tf">
      <Link to="/diet" className="tf-head">
        <span className="card-title"><DietIcon size={18} /> Food</span>
        <ChevronRight size={18} />
      </Link>

      {!data && <Skeleton lines={2} />}

      {data && (
        <>
          <div className="tf-nums">
            <span className="tf-eaten num">{eaten}</span>
            <span className="tf-of">of {target} kcal</span>
            <span className="tf-left num">{left < 0 ? `${-left} over` : `${left} left`}</span>
          </div>
          <div className="tf-bar" role="presentation">
            <span className={`tf-fill${left < 0 ? ' is-over' : ''}`} style={{ width: `${pct}%` }} />
          </div>
          {proteinShort > 0 && (
            <p className="muted small">{proteinShort} g of protein still to go today.</p>
          )}
        </>
      )}

      <div className="tf-actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setLogging(true)}>
          <PlusIcon size={16} /> Log a meal
        </button>
        <button
          type="button"
          className={`btn btn-sm ${checking ? 'btn-ghost' : 'btn-primary'}`}
          aria-expanded={checking}
          onClick={() => setChecking((c) => !c)}
        >
          <SparkIcon size={16} /> {checking ? 'Close' : 'Before you eat it'}
        </button>
      </div>

      {/* The same check as the Food page, without a second card around it. */}
      {checking && <PreMealCheck date={date} variant="inline" />}

      <LogMealSheet open={logging} onClose={() => setLogging(false)} date={date} />
    </section>
  )
}
