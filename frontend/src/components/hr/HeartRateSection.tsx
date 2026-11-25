/**
 * Heart rate, split by what you were doing.
 *
 * Rohit: "i wanna see how my hr is changing (heartbeat is increasing or
 * decreasing)" — asleep, running, walking, ordinary daytime.
 *
 * One line per context rather than one line for the day, because a day holds
 * four different hearts and averaging them hides the one that matters most.
 * Sleeping heart rate is the best day-to-day signal of fatigue, illness and
 * fitness, and it is also the slowest to move — which is exactly why it
 * disappears into a daily average of sixteen waking hours.
 *
 * Down is the win on every line here except running, where the question is
 * not "how low" but "how low at a given pace" — that comparison lives in
 * Health → Heart and is linked rather than duplicated.
 *
 * A day without enough readings is a gap, not a zero. A flat line through a
 * week the watch was off the wrist is a lie a chart tells convincingly.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../../lib/auth'
import { Empty, ErrorState, Skeleton } from '../States'

type Trend = {
  enough: boolean; from?: number; to?: number
  change?: number; better?: boolean; flat?: boolean
}
type Context = {
  key: string; label: string; why: string
  daily: { day: string; bpm: number; readings: number }[]
  weekly: { week: string; bpm: number; days: number }[]
  trend: Trend
}
type Payload = { days: number; contexts: Context[]; resting: { day: string; bpm: number }[]; note: string }

const RANGES = [28, 56, 180] as const
const RANGE_LABEL: Record<number, string> = { 28: '4 weeks', 56: '8 weeks', 180: '6 months' }

function TrendLine({ t, label }: { t: Trend; label: string }) {
  if (!t.enough) {
    return <p className="hrx-trend muted">Not enough days yet to call a direction.</p>
  }
  if (t.flat) {
    return <p className="hrx-trend">Holding around {t.to} bpm.</p>
  }
  return (
    <p className={`hrx-trend${t.better ? ' is-better' : ' is-worse'}`}>
      {t.from} → {t.to} bpm
      <span className="hrx-change">
        {' '}{t.better ? 'down' : 'up'} {Math.abs(t.change ?? 0)}
      </span>
      {/* Named, not signed: "-3" reads as worse to most people and this is
          the one place where down is the win. */}
      <span className="muted"> · {t.better ? 'the good direction' : `worth watching for ${label.toLowerCase()}`}</span>
    </p>
  )
}

export function HeartRateSection() {
  const [days, setDays] = useState<number>(56)
  const [by, setBy] = useState<'daily' | 'weekly'>('daily')

  const q = useQuery({
    queryKey: ['hr-contexts', days],
    queryFn: () => api<Payload>(`/health/heart-rate/?days=${days}`),
    placeholderData: (prev) => prev,
  })

  if (q.isLoading) return <section className="card"><Skeleton lines={6} /></section>
  if (q.isError) {
    return <ErrorState message="Heart rate did not load." onRetry={() => q.refetch()} />
  }
  const d = q.data!
  const anything = d.contexts.some((c) => c.daily.length > 0)

  return (
    <div className="stack hrx">
      <section className="card stack-sm">
        <div className="hrx-controls">
          <div className="seg-row" role="radiogroup" aria-label="Period">
            {RANGES.map((r) => (
              <button key={r} type="button" role="radio" aria-checked={days === r}
                      className={`seg-btn${days === r ? ' is-on' : ''}`}
                      onClick={() => setDays(r)}>{RANGE_LABEL[r]}</button>
            ))}
          </div>
          <div className="seg-row" role="radiogroup" aria-label="Grouping">
            {(['daily', 'weekly'] as const).map((k) => (
              <button key={k} type="button" role="radio" aria-checked={by === k}
                      className={`seg-btn${by === k ? ' is-on' : ''}`}
                      onClick={() => setBy(k)}>{k === 'daily' ? 'By day' : 'By week'}</button>
            ))}
          </div>
        </div>
        <p className="muted small">{d.note}</p>
      </section>

      {!anything && (
        <Empty title="No heart-rate data yet">
          This needs the all-day heart rate your watch records. Sync Garmin, and
          wear it overnight for the sleeping line.
        </Empty>
      )}

      {d.contexts.filter((c) => c.daily.length > 0).map((c) => {
        const points = by === 'daily'
          ? c.daily.map((p) => ({ x: p.day, bpm: p.bpm }))
          : c.weekly.map((p) => ({ x: p.week, bpm: p.bpm }))
        return (
          <section key={c.key} className="card stack-sm">
            <div className="row">
              <strong>{c.label}</strong>
              <span className="muted small">{points.length} {by === 'daily' ? 'days' : 'weeks'}</span>
            </div>
            <TrendLine t={c.trend} label={c.label} />
            <div className="hrx-chart">
              <ResponsiveContainer width="100%" height={150}>
                {/* No negative left margin: it clipped the axis labels to
                    ".1" and ".8". Three digits of bpm need the room. */}
                <LineChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="2 4" vertical={false} opacity={0.25} />
                  <XAxis dataKey="x" tick={{ fontSize: 10 }} tickLine={false} axisLine={false}
                         tickFormatter={(v: string) => v.slice(5)} minTickGap={24} />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false}
                         domain={['dataMin - 3', 'dataMax + 3']} width={34}
                         tickFormatter={(v: number) => String(Math.round(v))} />
                  <Tooltip formatter={(v) => [`${v} bpm`, c.label]} />
                  {/* No dots on the daily series: 56 of them is a smear. */}
                  <Line type="monotone" dataKey="bpm" stroke="currentColor" strokeWidth={2}
                        dot={by === 'weekly'} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="muted small">{c.why}</p>
          </section>
        )
      })}

      <section className="card stack-sm">
        <strong>Heart rate at a given pace</strong>
        <p className="muted small">
          The running line above goes up when you run harder, which is not the
          same as being less fit. The question that answers that — what your
          heart does at the <em>same</em> pace, now against before — is in{' '}
          <Link to="/health/heart">Heart</Link>.
        </p>
      </section>
    </div>
  )
}
