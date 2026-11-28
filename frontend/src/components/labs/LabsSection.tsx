/**
 * Blood and urine panels: your numbers, against the range they were measured
 * against, with the ones runners care about called out.
 *
 * It does not diagnose, and that is the shape of the screen rather than a
 * footnote on it. A marker outside a range is a question — ferritin of 18
 * means one thing in a man training hard and another in someone who has just
 * given blood, and the app knows neither. So every flag reads as something to
 * ask about, the standing note is on the page rather than hidden behind an
 * info button, and there is no "all clear": a handful of markers from one
 * morning is not a statement about anybody's health.
 *
 * The lab's own range always wins where the report printed one, because
 * reference intervals differ between labs and assays and a value flagged
 * against the wrong range is worse than no flag. Which range was used is shown
 * on every row.
 *
 * Entry is typed or uploaded, and the upload does not skip the typing so much
 * as pre-fill it: a PDF or photo comes back as a draft with every value in an
 * editable box and the text it was read from printed underneath (UploadReport).
 * The reason a photo was refused for a release and a half — a mis-read ferritin
 * is a number somebody might act on — is answered by never saving what the model
 * produced without him confirming it row by row.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { Empty, ErrorState, Skeleton } from '../States'
import { UploadReport } from './UploadReport'

type Marker = {
  key: string; label: string; unit: string
  matters: string; runner_key: boolean; typical: [number, number] | null
}
type Reading = {
  key: string; label: string; unit: string; value: number
  low: number | null; high: number | null
  range_source: 'lab' | 'fallback' | 'none'
  status: 'in_range' | 'below' | 'above' | 'unknown'
  flagged: boolean; matters: string; note: string; runner_key: boolean
}
type Panel = {
  id: number; taken_on: string; lab: string; note: string
  readings: Reading[]; headline: string
  missing_runner_markers: string[]; used_fallback_ranges: string[]
  standing_note: string
}
type Panels = { panels: Panel[]; trends: Record<string, { taken_on: string; value: number }[]>; standing_note: string }

const RANGE_SAID: Record<Reading['range_source'], string> = {
  lab: 'your lab’s range',
  fallback: 'a typical range — your report printed none',
  none: 'no range',
}

function Row({ r }: { r: Reading }) {
  return (
    <li className={`lab-row${r.flagged ? ' is-flagged' : ''}`}>
      <div className="lab-row-top">
        <span className="lab-name">{r.label}</span>
        <span className="lab-value num">
          {r.value}<span className="lab-unit"> {r.unit}</span>
        </span>
      </div>
      <p className="lab-range">
        {r.low != null || r.high != null
          ? <>{r.low ?? '–'}–{r.high ?? '–'} · {RANGE_SAID[r.range_source]}</>
          : RANGE_SAID.none}
        {r.status === 'below' && <span className="lab-tag">below</span>}
        {r.status === 'above' && <span className="lab-tag">above</span>}
      </p>
      <p className="lab-matters">{r.matters}</p>
      {/* Only on a flag, and always a question rather than a conclusion. */}
      {r.note && <p className="lab-ask">{r.note}</p>}
    </li>
  )
}

function AddPanel({ markers, onDone }: { markers: Marker[]; onDone: () => void }) {
  const client = useQueryClient()
  const [takenOn, setTakenOn] = useState(new Date().toISOString().slice(0, 10))
  const [lab, setLab] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [ranges, setRanges] = useState<Record<string, { low: string; high: string }>>({})

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<Panel>('/labs/', { method: 'POST', ...json(body) }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['labs'] })
      onDone()
    },
  })

  const entered = Object.entries(values).filter(([, v]) => v.trim() !== '')

  return (
    <div className="lab-add stack">
      <div className="goal-field">
        <label className="field-label" htmlFor="lab-date">Date of the test</label>
        <input id="lab-date" type="date" value={takenOn}
               onChange={(e) => setTakenOn(e.target.value)} />
      </div>
      <div className="goal-field">
        <label className="field-label" htmlFor="lab-name">Lab (optional)</label>
        <input id="lab-name" value={lab} placeholder="e.g. Thyrocare"
               onChange={(e) => setLab(e.target.value)} />
      </div>

      <p className="lab-hint">
        Type only what your report has. If it prints its own reference range,
        put it in — yours beats ours.
      </p>

      {markers.map((m) => (
        <div key={m.key} className={`lab-entry${m.runner_key ? ' is-key' : ''}`}>
          <label className="lab-entry-label" htmlFor={`m-${m.key}`}>
            {m.label} <span className="muted">{m.unit}</span>
            {m.runner_key && <span className="lab-key-tag">runners</span>}
          </label>
          <div className="lab-entry-row">
            <input
              id={`m-${m.key}`} type="number" step="any" inputMode="decimal"
              value={values[m.key] ?? ''}
              placeholder="value"
              onChange={(e) => setValues((v) => ({ ...v, [m.key]: e.target.value }))}
            />
            <input
              type="number" step="any" inputMode="decimal" className="lab-ref"
              value={ranges[m.key]?.low ?? ''} placeholder="low"
              onChange={(e) => setRanges((r) => ({
                ...r, [m.key]: { low: e.target.value, high: r[m.key]?.high ?? '' },
              }))}
            />
            <input
              type="number" step="any" inputMode="decimal" className="lab-ref"
              value={ranges[m.key]?.high ?? ''} placeholder="high"
              onChange={(e) => setRanges((r) => ({
                ...r, [m.key]: { low: r[m.key]?.low ?? '', high: e.target.value },
              }))}
            />
          </div>
        </div>
      ))}

      <button
        type="button" className="btn btn-primary btn-grow"
        disabled={!entered.length || save.isPending}
        onClick={() => save.mutate({
          taken_on: takenOn,
          lab: lab.trim(),
          readings: entered.map(([key, v]) => {
            const r = ranges[key]
            return {
              key, value: Number(v),
              ...(r?.low ? { ref_low: Number(r.low) } : {}),
              ...(r?.high ? { ref_high: Number(r.high) } : {}),
            }
          }),
        })}
      >
        {save.isPending ? 'Saving…' : `Save ${entered.length} result${entered.length === 1 ? '' : 's'}`}
      </button>
      {save.error && (
        <p className="small bad" role="alert">{errorText(save.error, 'Not saved.')}</p>
      )}
    </div>
  )
}

type Mode = null | 'type' | 'upload'

export function LabsSection() {
  const [mode, setMode] = useState<Mode>(null)
  const adding = mode === 'type'
  const panels = useQuery({ queryKey: ['labs'], queryFn: () => api<Panels>('/labs/') })
  const markers = useQuery({
    queryKey: ['lab-markers'],
    queryFn: () => api<{ markers: Marker[] }>('/labs/markers/'),
    enabled: adding,
  })
  const toggle = (next: Exclude<Mode, null>) => setMode((m) => (m === next ? null : next))

  return (
    <div className="stack labs">
      <section className="card stack">
        <div className="lab-head">
          <strong>Blood &amp; urine</strong>
          <span className="lab-add-btns">
            <button type="button" className="btn btn-primary btn-sm"
                    onClick={() => toggle('upload')}>
              {mode === 'upload' ? 'Cancel' : 'Upload a report'}
            </button>
            <button type="button" className="btn btn-secondary btn-sm"
                    onClick={() => toggle('type')}>
              {adding ? 'Cancel' : 'Type it in'}
            </button>
          </span>
        </div>
        {/* On the page, not behind an info button. */}
        <p className="lab-standing">{panels.data?.standing_note}</p>
        {mode === 'upload' && <UploadReport onSaved={() => setMode(null)} />}
        {adding && (markers.data
          ? <AddPanel markers={markers.data.markers} onDone={() => setMode(null)} />
          : <Skeleton lines={6} />)}
      </section>

      {panels.isLoading && <section className="card"><Skeleton lines={5} /></section>}
      {panels.isError && (
        <ErrorState message="Your panels did not load." onRetry={() => panels.refetch()} />
      )}

      {panels.data?.panels.length === 0 && mode === null && (
        <Empty title="No results yet">
          Add your first panel when you have one.
        </Empty>
      )}

      {panels.data?.panels.map((p) => (
        <section key={p.id} className="card stack">
          <div className="row">
            <strong>{new Date(`${p.taken_on}T00:00:00`).toLocaleDateString(undefined, {
              day: 'numeric', month: 'long', year: 'numeric',
            })}</strong>
            {p.lab && <span className="muted small">{p.lab}</span>}
          </div>
          <p className="lab-headline">{p.headline}</p>
          <ul className="lab-rows">
            {p.readings.map((r) => <Row key={r.key} r={r} />)}
          </ul>
          {!!p.missing_runner_markers.length && (
            <p className="muted small">
              Not in this panel, and worth asking for next time:{' '}
              {p.missing_runner_markers.join(', ').replace(/_/g, ' ')}.
            </p>
          )}
        </section>
      ))}
    </div>
  )
}
