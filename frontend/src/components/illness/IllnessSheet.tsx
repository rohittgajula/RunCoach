import { useEffect, useState } from 'react'
import { dur, parseDate, todayISO } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { ILLNESS_LABEL, useIllness, type Illness, type IllnessType } from '../../lib/r17'
import { useCancelIllness, useRecover, useStartIllness } from '../../lib/r17lazy'
import { BottomSheet } from '../BottomSheet'
import '../../styles/r17lazy.css'

const TYPES: IllnessType[] = ['cold', 'flu', 'stomach', 'injury', 'other']

/** Non-medical wording; the server's own advice wins when it sends one. */
const SEE_DOCTOR = [
  'you have a fever above 39 °C or one that lasts more than 3 days',
  'you have chest pain, a racing or irregular heartbeat, or feel faint',
  'you’re short of breath at rest',
  'you can’t keep fluids down for a day',
  'an injury swells a lot, you can’t put weight on it, or pain is getting worse',
]

function adviceFor(type: IllnessType, below: boolean): string {
  if (type === 'injury') return 'Rest the painful area. Walking and gentle moves that don’t hurt are fine; skip running until you can walk briskly without pain.'
  if (type === 'flu' || below) return 'With a fever or symptoms below the neck (chest, stomach, aching body), don’t run. Wait until you’ve been symptom-free for 24–48 hours.'
  return 'Symptoms only above the neck (runny nose, sneezing, mild sore throat): an easy walk is fine if you feel up to it. Rest is never wrong.'
}

const shortDay = (iso: string) => parseDate(iso).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

function Advice({ text, doctor }: { text: string | string[]; doctor?: string[] | null }) {
  const list = doctor?.length ? doctor : SEE_DOCTOR
  const lines = Array.isArray(text) ? text : [text]
  return (
    <div className="ill-advice">
      {lines.map((l) => <p key={l}>{l}</p>)}
      <p><b>See a doctor if…</b></p>
      <ul>{list.map((d) => <li key={d}>{d}</li>)}</ul>
      <p className="muted small">This is general guidance, not medical advice.</p>
    </div>
  )
}

function StartForm({ onDone }: { onDone: () => void }) {
  const start = useStartIllness()
  const [type, setType] = useState<IllnessType>('cold')
  const [below, setBelow] = useState(false)
  const [fever, setFever] = useState(false)
  const [from, setFrom] = useState(todayISO())
  const [days, setDays] = useState('')
  const submit = () =>
    start.mutate(
      {
        type,
        ...(type === 'injury' ? {} : { symptoms: below ? 'below_neck' as const : 'above_neck' as const, fever }),
        start_date: from,
        expected_days: days ? Math.max(1, Math.min(60, Number(days))) : null,
      },
      { onSuccess: onDone },
    )
  return (
    <div className="ill-form">
      <p className="muted">Your upcoming runs will be paused (and taken off your watch) until you say you’re better. Streaks won’t break.</p>
      <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="lbl" style={{ marginBottom: 8 }}>What’s going on?</legend>
        <div className="ill-types">
          {TYPES.map((t) => (
            <button key={t} type="button" aria-pressed={type === t} onClick={() => { setType(t); if (t === 'flu' || t === 'stomach') setBelow(true); setFever(t === 'flu') }}>
              {ILLNESS_LABEL[t]}
            </button>
          ))}
        </div>
      </fieldset>
      {type !== 'injury' && (
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="lbl" style={{ marginBottom: 4 }}>Where are the symptoms?</legend>
          <label className="ill-check"><input type="radio" name="ill-where" checked={!below} onChange={() => setBelow(false)} /><span>Only above the neck<small>Runny or blocked nose, sneezing, mild sore throat</small></span></label>
          <label className="ill-check"><input type="radio" name="ill-where" checked={below} onChange={() => setBelow(true)} /><span>Below the neck too<small>Chest, cough, aching body, stomach</small></span></label>
          <label className="ill-check"><input type="checkbox" checked={fever} onChange={(e) => setFever(e.target.checked)} /><span>I have a fever<small>Feeling hot and shivery, or 38 °C and above</small></span></label>
        </fieldset>
      )}
      <div className="ill-row">
        <label>Since<input type="date" value={from} max={todayISO()} onChange={(e) => setFrom(e.target.value || todayISO())} /></label>
        <label>Expected days (optional)<input type="number" inputMode="numeric" min={1} max={60} placeholder="e.g. 3" value={days} onChange={(e) => setDays(e.target.value)} /></label>
      </div>
      <Advice text={adviceFor(type, below || fever)} />
      {start.isError && <p className="bad small">{errorText(start.error, 'Couldn’t save. Try again.')}</p>}
      <div className="ill-foot">
        <button type="button" className="btn btn-primary" disabled={start.isPending} onClick={submit}>
          {start.isPending ? 'Pausing your plan…' : 'Pause my plan'}
        </button>
      </div>
    </div>
  )
}

function ReturnPreview({ illness, onDone }: { illness: Illness; onDone: () => void }) {
  const recover = useRecover(illness.id)
  const [preview, setPreview] = useState<Illness>()
  const { mutate } = recover
  useEffect(() => {
    mutate(true, { onSuccess: setPreview })
  }, [mutate])
  const p = preview
  const block = p?.return_block
  if (!p) {
    return recover.isError
      ? <div className="stack"><p className="bad">{errorText(recover.error, 'Couldn’t build your return plan.')}</p><button type="button" className="btn btn-secondary" onClick={() => mutate(true, { onSuccess: setPreview })}>Try again</button></div>
      : <p className="thinking">Building a gentle way back…</p>
  }
  return (
    <div className="ill-form">
      <p>
        <b>{p.days_off ?? illness.days_so_far} {(p.days_off ?? illness.days_so_far) === 1 ? 'day' : 'days'} off.</b>{' '}
        {block ? <>Here’s a gentle way back: <b>{block.label.toLowerCase()}</b>.</> : 'Ease back in gently.'}
      </p>
      {p.race_warning && <p className="ill-warn" role="alert">{p.race_warning.text}</p>}
      {block && (
        <ul className="ill-sessions">
          {block.sessions.map((s) => (
            <li key={`${s.date}-${s.title}`}>
              <span className="ill-day">{shortDay(s.date)}</span>
              <span>
                <b className="block">{s.title}</b>
                <span className="muted small">{dur(s.duration_s)}{s.kind === 'RUN_WALK' ? ' · run 2 min / walk 1 min' : ''}{s.pct_of_usual ? ` · ${s.pct_of_usual}% of usual` : ''}</span>
              </span>
              {s.hr_cap != null ? <span className="ill-cap">HR ≤ {s.hr_cap}</span> : <span />}
            </li>
          ))}
        </ul>
      )}
      {block?.note && <p className="muted small">{block.note}</p>}
      {block?.resumes_on && <p className="muted small">Your normal plan picks up again from {shortDay(block.resumes_on)}.</p>}
      <p className="muted small">Stop and walk if you feel dizzy, your chest feels tight or your heart rate won’t settle. This is general guidance, not medical advice.</p>
      {recover.isError && <p className="bad small">{errorText(recover.error, 'Couldn’t save. Try again.')}</p>}
      <div className="ill-foot">
        <button type="button" className="btn btn-secondary" onClick={onDone}>Not yet</button>
        <button type="button" className="btn btn-primary" disabled={recover.isPending} onClick={() => recover.mutate(false, { onSuccess: onDone })}>
          {recover.isPending ? 'Updating your plan…' : 'Start this plan'}
        </button>
      </div>
    </div>
  )
}

function ActiveInfo({ illness, onDone }: { illness: Illness; onDone: () => void }) {
  const cancel = useCancelIllness()
  const [confirm, setConfirm] = useState(false)
  return (
    <div className="stack">
      <p>You’re in rest mode since {shortDay(illness.start_date)} ({illness.type_label || ILLNESS_LABEL[illness.type]}).</p>
      <Advice text={illness.advice?.length ? illness.advice : adviceFor(illness.type, illness.symptoms === 'below_neck' || illness.fever)} doctor={illness.see_doctor} />
      {confirm ? (
        <div className="cm-confirm">
          <p>Undo rest mode? Your paused runs go back into the plan as they were.</p>
          <div className="ill-foot">
            <button type="button" className="btn btn-secondary" onClick={() => setConfirm(false)}>Keep resting</button>
            <button type="button" className="btn btn-solid-bad" disabled={cancel.isPending} onClick={() => cancel.mutate(illness.id, { onSuccess: onDone })}>Undo</button>
          </div>
          {cancel.isError && <p className="bad small">{errorText(cancel.error, 'Couldn’t undo.')}</p>}
        </div>
      ) : (
        <button type="button" className="btn btn-ghost" onClick={() => setConfirm(true)}>Started this by mistake?</button>
      )}
    </div>
  )
}

/**
 * R17 §10: "I’m sick / injured" form, or — when an illness is active — "I’m better" →
 * return-to-run preview (dry run) → confirm.
 */
export default function IllnessSheet({ open, onClose, mode }: { open: boolean; onClose: () => void; mode: 'start' | 'recover' }) {
  const ill = useIllness()
  const active = ill.data?.active ?? null
  const recovering = mode === 'recover' && active
  return (
    <BottomSheet open={open} onClose={onClose} title={recovering ? 'Back to running' : 'Sick or injured'}>
      {open && (ill.isPending ? <p className="thinking">Loading…</p> : recovering ? <ReturnPreview illness={active} onDone={onClose} />
        : active ? <ActiveInfo illness={active} onDone={onClose} /> : <StartForm onDone={onClose} />)}
    </BottomSheet>
  )
}
