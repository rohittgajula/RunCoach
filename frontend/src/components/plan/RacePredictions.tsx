/**
 * Garmin's race prediction beside ours, and why they disagree.
 *
 * Both numbers were already in the database and had never shared a screen.
 * Garmin's live under Health as a fitness readout; ours is only produced for a
 * saved race, which somebody training without one does not have. So the plain
 * question — how fast could I do a 5k — had two answers stored and nowhere to
 * read them.
 *
 * They disagree, and the disagreement is the content. Garmin says 46:03 for
 * Rohit's 5k, which is 9:13 per kilometre held for the whole distance; his
 * longest unbroken run is 11:39. Garmin is not wrong about his engine — it is
 * answering a question about a runner who runs the whole way.
 *
 * So the two are framed as different questions rather than a contest, and the
 * gap between them is labelled for what it is: mostly walking, not fitness, and
 * the thing the plan is built to close.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/auth'
import { Skeleton } from '../States'

type Ours = {
  mode: 'CONTINUOUS' | 'RUN_WALK' | 'INSUFFICIENT_DATA'
  confidence: 'NONE' | 'LOW' | 'MODERATE'
  basis: string
  likely_finish_s: number | null
  range_s: [number, number] | null
}

type Row = {
  key: string
  distance_km: number
  garmin_s: number | null
  ours: Ours
  gap_s: number | null
}

type Payload = {
  garmin_as_of: string | null
  garmin_stale: boolean
  garmin_age_days: number | null
  distances: Row[]
  explanation: {
    garmin_assumes: string
    ours_assumes: string
    longest_unbroken_s: number
    why_they_differ: string | null
  } | null
}

const LABEL: Record<string, string> = {
  '5k': '5 km', '10k': '10 km', half: 'Half marathon', marathon: 'Marathon',
}

function hms(seconds: number | null | undefined): string {
  if (!seconds) return '—'
  const whole = Math.round(seconds)
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = whole % 60
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
}

export function RacePredictions() {
  const query = useQuery<Payload>({
    queryKey: ['race-predictions'],
    queryFn: () => api('/plan/race-predictions/'),
  })

  if (query.isPending) return <section className="card"><Skeleton lines={5} /></section>
  if (query.isError || !query.data) return null

  const { distances, explanation, garmin_stale, garmin_age_days } = query.data
  const usable = distances.filter((d) => d.garmin_s || d.ours.range_s)
  if (usable.length === 0) return null

  return (
    <section className="card predictions">
      <h2>How fast could you go?</h2>
      <p className="small muted">
        Two answers to the same question, because they are not quite the same
        question.
      </p>

      <div className="pred-grid">
        <span className="pg-h">Distance</span>
        <span className="pg-h r">Garmin</span>
        <span className="pg-h r">Ours</span>

        {usable.map((row) => (
          <Row key={row.key} row={row} />
        ))}
      </div>

      {garmin_stale && garmin_age_days != null && (
        <p className="small warn pred-stale">
          Garmin's estimate is {garmin_age_days} days old — it stops updating
          without sustained running, so treat it as a reading from then.
        </p>
      )}

      {explanation && (
        <div className="pred-why">
          <p className="small"><strong>Garmin</strong> — {explanation.garmin_assumes}</p>
          <p className="small"><strong>Ours</strong> — {explanation.ours_assumes}</p>
          {explanation.why_they_differ && (
            <p className="small pred-gap">{explanation.why_they_differ}</p>
          )}
        </div>
      )}
    </section>
  )
}

function Row({ row }: { row: Row }) {
  const insufficient = row.ours.mode === 'INSUFFICIENT_DATA'
  return (
    <>
      <span className="pg-l">
        {LABEL[row.key] ?? row.key}
        {row.ours.mode === 'RUN_WALK' && (
          <small>ours assumes run/walk</small>
        )}
      </span>
      <span className="pg-v num">{hms(row.garmin_s)}</span>
      <span className="pg-v num">
        {insufficient ? (
          <em className="pred-none">not enough data</em>
        ) : row.ours.range_s ? (
          <>
            {hms(row.ours.range_s[0])}–{hms(row.ours.range_s[1])}
            <small className="pred-conf">{row.ours.confidence.toLowerCase()} confidence</small>
          </>
        ) : '—'}
      </span>
    </>
  )
}
