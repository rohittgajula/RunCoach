/**
 * Upload the report, then check what was read off it.
 *
 * The typed form stays, and this does not replace it — it fills it in. Every
 * number arrives in an input he can correct, with the text it was read from
 * printed underneath, so confirming a panel is a glance down the page against
 * the paper in his hand rather than a second typing of it.
 *
 * The parts that are deliberately loud:
 *
 *   as printed   the literal characters from the report, under every value.
 *                If the report says 12.4 and the box says 124, that is visible
 *                without him working out which number is wrong.
 *   converted    vitamin D in nmol/L is a different number from the same result
 *                in ng/mL, by a factor of 2.5. When the server converted, the
 *                row says so and shows the original.
 *   couldn't     rows that failed a check, markers the app does not track, and
 *                anything illegible — all listed. A draft that is quietly four
 *                rows short is the worst outcome here, because a ferritin that
 *                was dropped looks exactly like a ferritin that was never tested.
 *
 * Nothing is saved until he presses save, and the file is never stored at all.
 */

import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../../lib/auth'
import { errorText } from '../../lib/queries'

type DraftReading = {
  key: string; label: string; unit: string; value: number
  as_printed: string; printed_name: string; printed_unit: string
  unit_note: string | null
  ref_low: number | null; ref_high: number | null
  runner_key: boolean
}
type Draft = {
  taken_on: string | null
  date_note: string | null
  lab: string
  readings: DraftReading[]
  rejected: { printed_name: string; reason: string }[]
  not_tracked: string[]
  unreadable: string[]
  missing_runner_markers: string[]
  source_note: string
  standing_note: string
}

type Edited = { value: string; low: string; high: string; keep: boolean }

const ACCEPT = 'application/pdf,image/*'

function startRow(r: DraftReading): Edited {
  return {
    value: String(r.value),
    low: r.ref_low == null ? '' : String(r.ref_low),
    high: r.ref_high == null ? '' : String(r.ref_high),
    keep: true,
  }
}

export function UploadReport({ onSaved }: { onSaved: () => void }) {
  const client = useQueryClient()
  const picker = useRef<HTMLInputElement>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [rows, setRows] = useState<Record<string, Edited>>({})
  const [takenOn, setTakenOn] = useState('')
  const [lab, setLab] = useState('')

  const read = useMutation({
    // api() handles the multipart boundary and the 401-refresh replay; a raw
    // fetch here would drop him at the login screen on a stale access token,
    // mid-upload, with the file gone.
    mutationFn: (file: File) => {
      const body = new FormData()
      body.append('file', file)
      return api<Draft>('/labs/extract/', { method: 'POST', body })
    },
    onSuccess: (d) => {
      setDraft(d)
      setRows(Object.fromEntries(d.readings.map((r) => [r.key, startRow(r)])))
      setTakenOn(d.taken_on ?? '')
      setLab(d.lab ?? '')
    },
  })

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api('/labs/', { method: 'POST', ...json(body) }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['labs'] })
      onSaved()
    },
  })

  const set = (key: string, patch: Partial<Edited>) =>
    setRows((r) => ({ ...r, [key]: { ...r[key], ...patch } }))

  const keeping = draft?.readings.filter((r) => rows[r.key]?.keep && rows[r.key]?.value.trim() !== '') ?? []
  const canSave = keeping.length > 0 && !!takenOn

  if (!draft) {
    return (
      <div className="lab-up stack">
        <p className="lab-hint">
          A PDF from the lab, or a photo of the printout. Every number it reads comes
          back for you to check before anything is saved, and the file itself is not kept.
        </p>
        <input
          ref={picker} type="file" accept={ACCEPT} className="visually-hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) read.mutate(file)
            e.target.value = ''
          }}
        />
        <button
          type="button" className="btn btn-primary btn-grow"
          disabled={read.isPending}
          onClick={() => picker.current?.click()}
        >
          {read.isPending ? 'Reading your report…' : 'Choose a PDF or photo'}
        </button>
        {read.isPending && (
          <p className="muted small">This takes a few seconds — it is reading the whole page.</p>
        )}
        {read.error && (
          <p className="small bad" role="alert">
            {errorText(read.error, 'Could not read that file.')} You can still type the results in.
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="lab-up stack">
      <p className="lab-standing">{draft.standing_note}</p>
      <p className="muted small">{draft.source_note}</p>

      <div className="goal-field">
        <label className="field-label" htmlFor="up-date">Date of the test</label>
        <input id="up-date" type="date" value={takenOn} onChange={(e) => setTakenOn(e.target.value)} />
        {draft.date_note && <p className="lab-note-warn">{draft.date_note} — set it yourself.</p>}
      </div>
      <div className="goal-field">
        <label className="field-label" htmlFor="up-lab">Lab</label>
        <input id="up-lab" value={lab} placeholder="e.g. Thyrocare" onChange={(e) => setLab(e.target.value)} />
      </div>

      {draft.readings.length > 0 && (
        <>
          <p className="lab-hint">
            <strong>Check each number against your report.</strong> What the report
            printed is shown under each box.
          </p>
          {draft.readings.map((r) => {
            const row = rows[r.key] ?? startRow(r)
            const changed = row.value.trim() !== String(r.value)
            return (
              <div key={r.key} className={`lab-entry lab-up-row${r.runner_key ? ' is-key' : ''}${row.keep ? '' : ' is-off'}`}>
                <label className="lab-entry-label" htmlFor={`up-${r.key}`}>
                  {r.label} <span className="muted">{r.unit}</span>
                  {r.runner_key && <span className="lab-key-tag">runners</span>}
                </label>
                <div className="lab-entry-row">
                  <input
                    id={`up-${r.key}`} type="number" step="any" inputMode="decimal"
                    value={row.value} disabled={!row.keep}
                    onChange={(e) => set(r.key, { value: e.target.value })}
                  />
                  <input
                    type="number" step="any" inputMode="decimal" className="lab-ref"
                    value={row.low} placeholder="low" disabled={!row.keep}
                    onChange={(e) => set(r.key, { low: e.target.value })}
                  />
                  <input
                    type="number" step="any" inputMode="decimal" className="lab-ref"
                    value={row.high} placeholder="high" disabled={!row.keep}
                    onChange={(e) => set(r.key, { high: e.target.value })}
                  />
                </div>
                <p className="lab-asprinted">
                  Your report: <strong>{r.printed_name}</strong>
                  {r.as_printed && <> &nbsp;<span className="lab-printed-val">{r.as_printed}</span></>}
                  {r.printed_unit && <> {r.printed_unit}</>}
                  {changed && <span className="lab-tag">edited</span>}
                </p>
                {r.unit_note && <p className="lab-note-warn">{r.unit_note}</p>}
                <button
                  type="button" className="lab-skip"
                  onClick={() => set(r.key, { keep: !row.keep })}
                >
                  {row.keep ? 'Leave this one out' : 'Put it back'}
                </button>
              </div>
            )
          })}
        </>
      )}

      {draft.readings.length === 0 && (
        <p className="lab-note-warn">
          Nothing on that file came through as a result I could use. Have a look at
          what it could not read, below, and type the panel in instead.
        </p>
      )}

      {draft.rejected.length > 0 && (
        <div className="lab-cant">
          <p className="lab-cant-head">Left out, because the number did not add up</p>
          <ul>
            {draft.rejected.map((x, i) => (
              <li key={`${x.printed_name}-${i}`}><strong>{x.printed_name}</strong> — {x.reason}</li>
            ))}
          </ul>
          <p className="muted small">Type any of these in by hand once you have saved this panel.</p>
        </div>
      )}

      {draft.unreadable.length > 0 && (
        <p className="muted small">Could not read on the page: {draft.unreadable.join(', ')}.</p>
      )}
      {draft.not_tracked.length > 0 && (
        <p className="muted small">
          On your report but not tracked here: {draft.not_tracked.join(', ')}.
        </p>
      )}
      {draft.missing_runner_markers.length > 0 && (
        <p className="muted small">
          Not found in this report, and worth asking for next time:{' '}
          {draft.missing_runner_markers.join(', ')}.
        </p>
      )}

      <div className="row lab-up-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setDraft(null); read.reset() }}>
          Start over
        </button>
        <button
          type="button" className="btn btn-primary btn-grow"
          disabled={!canSave || save.isPending}
          onClick={() => save.mutate({
            taken_on: takenOn,
            lab: lab.trim(),
            readings: keeping.map((r) => {
              const row = rows[r.key]
              return {
                key: r.key,
                value: Number(row.value),
                unit: r.unit,
                ...(row.low.trim() ? { ref_low: Number(row.low) } : {}),
                ...(row.high.trim() ? { ref_high: Number(row.high) } : {}),
              }
            }),
          })}
        >
          {save.isPending ? 'Saving…' : `Save ${keeping.length} result${keeping.length === 1 ? '' : 's'}`}
        </button>
      </div>
      {!takenOn && <p className="lab-note-warn">Set the date of the test before saving.</p>}
      {save.error && <p className="small bad" role="alert">{errorText(save.error, 'Not saved.')}</p>}
    </div>
  )
}
