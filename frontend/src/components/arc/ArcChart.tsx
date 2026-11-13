/**
 * The arc: what you have done and what the plan asks for, on one axis.
 *
 * Two quantities are drawn and they do not share a scale.
 *
 *   Bars    weekly running time. Solid for weeks that have happened, hollow for
 *           weeks the plan has committed to. Walking is already out of these —
 *           they are time spent running, not time out of the house.
 *   Line    the longest unbroken run block in that week. Solid behind today,
 *           dashed ahead of it, because ahead of today it is a target rather
 *           than a fact.
 *
 * The horizontal rule is the longest block on record. It sits above the recent
 * line on purpose: it is the shape of five weeks away from running, and hiding
 * it would make the last month look like progress rather than recovery.
 *
 * Today is a hard vertical divide. Everything left of it happened; everything
 * right of it is a plan. That is the one distinction the whole view exists to
 * make, so it is drawn as a line and not as a colour difference alone.
 */

import { useId } from 'react'
import {
  Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { duration, dur, monthDay } from '../../lib/format'
import type { ArcWeek } from '../../lib/types'

type Row = {
  start: string
  label: string
  past: boolean
  current: boolean
  /** Only one of these two is ever set, so the bars never stack. */
  doneMin: number | null
  planMin: number | null
  blockMin: number | null
  targetMin: number | null
  best: number
  week: ArcWeek
}

const toRows = (weeks: ArcWeek[]): Row[] =>
  weeks.map((w) => {
    const settled = w.past || w.current
    return {
      start: w.start,
      label: monthDay(w.start),
      past: w.past,
      current: w.current,
      doneMin: settled && w.done.run_s ? Math.round(w.done.run_s / 60) : null,
      planMin: !w.past && w.planned.run_s ? Math.round(w.planned.run_s / 60) : null,
      blockMin: settled && w.done.longest_run_s ? w.done.longest_run_s / 60 : null,
      targetMin: !w.past && w.planned.block_s ? w.planned.block_s / 60 : null,
      best: w.best_run_s / 60,
      week: w,
    }
  })

function ArcTip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null
  const { week } = payload[0].payload
  const ran = week.done.run_s > 0
  return (
    <div className="arc-tip">
      <p className="arc-tip-when">
        {monthDay(week.start)} – {monthDay(week.end)}
        {week.current ? ' · this week' : ''}
      </p>
      {ran && (
        <p>
          <b>{dur(week.done.run_s)}</b> running over {week.done.runs}{' '}
          {week.done.runs === 1 ? 'run' : 'runs'}
        </p>
      )}
      {ran && week.done.longest_run_s > 0 && (
        <p>Longest block <b>{duration(week.done.longest_run_s)}</b></p>
      )}
      {!week.past && week.planned.run_s > 0 && (
        <p>
          Plan asks <b>{dur(week.planned.run_s)}</b> over {week.planned.runs}{' '}
          {week.planned.runs === 1 ? 'run' : 'runs'}
        </p>
      )}
      {!week.past && week.planned.block_s > 0 && (
        <p>Target block <b>{duration(week.planned.block_s)}</b></p>
      )}
      {week.planned.gym > 0 && (
        <p>{week.done.gym}/{week.planned.gym} gym {week.planned.gym === 1 ? 'day' : 'days'}</p>
      )}
      {week.missed > 0 && (
        <p className="arc-tip-miss">
          {week.missed} missed · lost, not owed
        </p>
      )}
    </div>
  )
}

export function ArcChart({ weeks, bestS }: { weeks: ArcWeek[]; bestS: number }) {
  const id = useId()
  const rows = toRows(weeks)
  if (rows.length < 2) return null

  const current = rows.find((r) => r.current)
  const bestMin = bestS / 60

  // Both series are minutes, so one axis is honest — but the block line lives in
  // single digits while weekly volume runs to forty, and a shared axis flattens
  // the line to nothing. Hence a second axis, and hence the two colours being
  // the only thing that ties a number to its scale.
  return (
    <div className="arc-chart">
      <ResponsiveContainer width="100%" height={236}>
        {/* No negative left margin. It was pulling the volume axis off the
            left edge, which clipped the digits and left every tick reading as a
            bare "m" — an axis labelled with its unit and no numbers. */}
        <ComposedChart data={rows} margin={{ top: 12, right: 8, bottom: 2, left: 0 }}>
          <defs>
            <pattern id={`${id}-plan`} width="5" height="5" patternTransform="rotate(45)"
              patternUnits="userSpaceOnUse">
              <line x1="0" y1="0" x2="0" y2="5" stroke="var(--arc-plan)" strokeWidth="2.4" />
            </pattern>
          </defs>
          <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="label" tick={{ fontSize: 10, fill: 'var(--muted)' }}
            axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={18}
          />
          <YAxis
            yAxisId="vol" tick={{ fontSize: 10, fill: 'var(--muted)' }}
            axisLine={false} tickLine={false} width={38}
            tickFormatter={(v: number) => (v ? `${v}m` : '')}
          />
          <YAxis yAxisId="block" orientation="right" hide />
          <Tooltip content={<ArcTip />} cursor={{ fill: 'var(--arc-cursor)' }} />

          {bestMin > 0 && (
            <ReferenceLine
              yAxisId="block" y={bestMin} stroke="var(--arc-best)" strokeDasharray="4 4"
              label={{
                value: `best ${duration(bestS)}`, position: 'insideBottomRight',
                fill: 'var(--arc-best)', fontSize: 10, offset: 5,
              }}
            />
          )}
          {current && (
            <ReferenceLine
              yAxisId="vol" x={current.label} stroke="var(--fg)" strokeWidth={1.5}
              label={{ value: 'today', position: 'insideTop', fill: 'var(--fg)', fontSize: 10 }}
            />
          )}

          <Bar yAxisId="vol" dataKey="doneMin" name="Ran" fill="var(--arc-done)"
            radius={[3, 3, 0, 0]} maxBarSize={22} />
          <Bar yAxisId="vol" dataKey="planMin" name="Planned" fill={`url(#${id}-plan)`}
            stroke="var(--arc-plan)" strokeWidth={1} radius={[3, 3, 0, 0]} maxBarSize={22} />

          <Line yAxisId="block" type="monotone" dataKey="blockMin" name="Longest block"
            stroke="var(--arc-block)" strokeWidth={2.4} dot={{ r: 2.6, strokeWidth: 0 }}
            activeDot={{ r: 4 }} connectNulls={false} />
          <Line yAxisId="block" type="monotone" dataKey="targetMin" name="Target block"
            stroke="var(--arc-block)" strokeWidth={2} strokeDasharray="4 4"
            dot={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>

      <ul className="arc-key">
        <li><i className="arc-sw arc-sw-done" />Ran</li>
        <li><i className="arc-sw arc-sw-plan" />Planned</li>
        <li><i className="arc-sw arc-sw-block" />Longest block</li>
        <li><i className="arc-sw arc-sw-target" />Target block</li>
      </ul>
    </div>
  )
}
