/**
 * The arc, as two charts rather than one.
 *
 * It was one chart: weekly running time as bars on a left axis, longest
 * unbroken block as a line on a hidden right axis, past solid and future
 * dashed, with a record line and a today line over the top. Every number on it
 * was correct and nobody could read it — because both quantities are measured
 * in minutes, so a 10-minute block and 10 minutes of running a week were drawn
 * at the same height while meaning entirely different things, and the line had
 * no visible axis to check it against.
 *
 * Hiding the second axis is what broke it. Two scales was the honest choice;
 * drawing them on top of each other was not. So: two charts, one quantity
 * each, both axes visible, each with a sentence saying what it is.
 *
 * The block chart goes first. It is the number this whole plan is built
 * around, and weekly volume is the means rather than the end.
 */

import {
  Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { duration, dur, monthDay } from '../../lib/format'
import type { ArcWeek } from '../../lib/types'

type Row = {
  start: string
  label: string
  past: boolean
  current: boolean
  blockMin: number | null
  targetMin: number | null
  doneMin: number | null
  planMin: number | null
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
      blockMin: settled && w.done.longest_run_s ? w.done.longest_run_s / 60 : null,
      targetMin: !w.past && w.planned.block_s ? w.planned.block_s / 60 : null,
      doneMin: settled && w.done.run_s ? Math.round(w.done.run_s / 60) : null,
      planMin: !w.past && w.planned.run_s ? Math.round(w.planned.run_s / 60) : null,
      week: w,
    }
  })

/** m:ss from minutes — an axis that reads 6:30, not 6.5. */
const clock = (min: number) => {
  const total = Math.round(min * 60)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function BlockTip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null
  const { week } = payload[0].payload
  const held = week.done.longest_run_s
  const target = week.planned.block_s
  return (
    <div className="arc-tip">
      <p className="arc-tip-when">week of {monthDay(week.start)}</p>
      {held > 0 && <p>Held <b>{duration(held)}</b> without stopping</p>}
      {!held && week.past && <p>Nothing recorded</p>}
      {!week.past && target > 0 && <p>Plan asks for <b>{duration(target)}</b></p>}
    </div>
  )
}

function VolumeTip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null
  const { week } = payload[0].payload
  return (
    <div className="arc-tip">
      <p className="arc-tip-when">week of {monthDay(week.start)}</p>
      {week.done.runs > 0 && (
        <p><b>{dur(week.done.run_s)}</b> running over {week.done.runs}{' '}
          {week.done.runs === 1 ? 'run' : 'runs'}</p>
      )}
      {week.past && !week.done.runs && <p>Nothing recorded</p>}
      {!week.past && week.planned.runs > 0 && (
        <p>Plan asks <b>{dur(week.planned.run_s)}</b> over {week.planned.runs}{' '}
          {week.planned.runs === 1 ? 'run' : 'runs'}</p>
      )}
      {week.planned.gym > 0 && (
        <p>{week.done.gym}/{week.planned.gym} gym {week.planned.gym === 1 ? 'day' : 'days'}</p>
      )}
      {week.missed > 0 && <p className="arc-tip-miss">{week.missed} missed</p>}
    </div>
  )
}

const AXIS = { fontSize: 10, fill: 'var(--muted)' } as const

/** The longest unbroken run, week by week. One line, one axis, in m:ss. */
export function BlockChart({ weeks, bestS }: { weeks: ArcWeek[]; bestS: number }) {
  const rows = toRows(weeks)
  if (rows.length < 2) return null
  const current = rows.find((r) => r.current)
  const bestMin = bestS / 60

  return (
    <figure className="arc-fig">
      <figcaption className="arc-cap">
        <b>Longest unbroken run</b>
        <span>How long you can run without walking. Solid is what you did, dashed is what the plan asks for next.</span>
      </figcaption>
      <ResponsiveContainer width="100%" height={176}>
        <ComposedChart data={rows} margin={{ top: 14, right: 10, bottom: 2, left: 0 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false}
            interval="preserveStartEnd" minTickGap={22} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44}
            tickFormatter={(v: number) => (v ? clock(v) : '')} />
          <Tooltip content={<BlockTip />} cursor={{ stroke: 'var(--line-2, var(--line))' }} />

          {bestMin > 0 && (
            <ReferenceLine y={bestMin} stroke="var(--arc-best)" strokeDasharray="4 4"
              label={{ value: `best ${duration(bestS)}`, position: 'insideBottomRight',
                fill: 'var(--arc-best)', fontSize: 10, offset: 5 }} />
          )}
          {current && (
            <ReferenceLine x={current.label} stroke="var(--fg)" strokeWidth={1.5}
              label={{ value: 'today', position: 'insideTop', fill: 'var(--fg)', fontSize: 10 }} />
          )}

          <Line type="monotone" dataKey="blockMin" name="Held" stroke="var(--arc-block)"
            strokeWidth={2.6} dot={{ r: 3, strokeWidth: 0 }} activeDot={{ r: 5 }}
            connectNulls={false} />
          <Line type="monotone" dataKey="targetMin" name="Target" stroke="var(--arc-block)"
            strokeWidth={2} strokeDasharray="4 4" dot={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  )
}

/** Time spent running each week. Bars only — nothing shares this axis. */
export function VolumeChart({ weeks }: { weeks: ArcWeek[] }) {
  const rows = toRows(weeks)
  if (rows.length < 2) return null
  const current = rows.find((r) => r.current)

  return (
    <figure className="arc-fig">
      <figcaption className="arc-cap">
        <b>Running time a week</b>
        <span>Minutes actually spent running, walking taken out. Solid bars happened; outlined bars are planned.</span>
      </figcaption>
      <ResponsiveContainer width="100%" height={158}>
        <BarChart data={rows} margin={{ top: 10, right: 10, bottom: 2, left: 0 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false}
            interval="preserveStartEnd" minTickGap={22} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={34}
            tickFormatter={(v: number) => (v ? String(v) : '')} />
          <Tooltip content={<VolumeTip />} cursor={{ fill: 'var(--arc-cursor)' }} />
          {current && (
            <ReferenceLine x={current.label} stroke="var(--fg)" strokeWidth={1.5}
              label={{ value: 'today', position: 'insideTop', fill: 'var(--fg)', fontSize: 10 }} />
          )}
          <Bar dataKey="doneMin" name="Ran" fill="var(--arc-done)" radius={[3, 3, 0, 0]} maxBarSize={20} />
          <Bar dataKey="planMin" name="Planned" fill="transparent" stroke="var(--arc-plan)"
            strokeWidth={1.4} radius={[3, 3, 0, 0]} maxBarSize={20} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}
