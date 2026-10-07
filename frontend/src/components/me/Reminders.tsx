import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { currentSubscription, isIOS, isStandalone, pushSupported, subscribe } from '../../lib/push'
import { errorText, subscribePush, testPush, unsubscribePush, usePatchReminders, useReminders } from '../../lib/queries'
import type { Nudge, Reminder, RemindersResponse } from '../../lib/types'
import { AlarmRemindersCard } from '../alarm/AlarmCards'
import { BellIcon, ChevronRight } from '../Icons'
import { CardHead, Pill } from '../Kit'
import { Empty, ErrorState, Skeleton } from '../States'

/** Is this device subscribed? (undefined while checking) */
function useDeviceSubscribed(): [boolean | undefined, (v: boolean) => void] {
  const [on, setOn] = useState<boolean | undefined>(undefined)
  useEffect(() => {
    let alive = true
    currentSubscription().then((s) => alive && setOn(!!s)).catch(() => alive && setOn(false))
    return () => { alive = false }
  }, [])
  return [on, setOn]
}

function ReminderRow({ r, onPatch, disabled }: { r: Reminder; onPatch: (patch: Partial<Reminder>) => void; disabled: boolean }) {
  const [time, setTime] = useState(r.time)
  useEffect(() => setTime(r.time), [r.time])
  return (
    <div className="reminder-row">
      <span className="grow">
        <strong>{r.label}</strong>
        <span className="muted small block">{r.description}</span>
      </span>
      <input
        type="time"
        aria-label={`${r.label} time`}
        value={time}
        disabled={disabled || !r.enabled}
        onChange={(e) => setTime(e.target.value)}
        onBlur={() => time && time !== r.time && onPatch({ time })}
      />
      <button
        type="button"
        role="switch"
        aria-checked={r.enabled}
        aria-label={r.label}
        disabled={disabled}
        className={`switch ${r.enabled ? 'is-on' : ''}`}
        onClick={() => onPatch({ enabled: !r.enabled })}
      />
    </div>
  )
}

/** Me → Reminders: allow notifications on this device, then per-reminder toggles + times. */
export function RemindersSection() {
  const reminders = useReminders()
  const patch = usePatchReminders()
  const [subscribed, setSubscribed] = useDeviceSubscribed()
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const data = reminders.data

  if (reminders.isPending) return <section className="card"><Skeleton lines={4} /></section>
  if (reminders.isError) return <ErrorState message={errorText(reminders.error)} onRetry={() => reminders.refetch()} />
  if (!data || !data.available) {
    return (
      <div className="stack">
        <Empty icon={<BellIcon size={32} />} title="Reminders aren’t switched on here">Push notifications aren’t set up on this server yet.</Empty>
        <AlarmRemindersCard />
      </div>
    )
  }

  const iosBlocked = isIOS() && !isStandalone()
  const enable = async () => {
    if (!data.public_key) return
    setBusy(true)
    setMessage('')
    const out = await subscribe(data.public_key)
    if (out.ok) {
      try {
        await subscribePush(out.subscription.toJSON())
        setSubscribed(true)
        reminders.refetch()
      } catch (error) {
        setMessage(errorText(error, 'Could not save this device.'))
      }
    } else {
      setMessage(
        out.reason === 'denied' ? 'Notifications are blocked for RunCoach. Allow them in your browser or phone settings, then try again.'
          : out.reason === 'no-worker' ? 'Open the installed app (or reload once) so the background worker can start, then try again.'
            : out.reason === 'unsupported' ? 'This browser can’t receive push notifications.'
              : out.message ?? 'Could not turn on notifications.',
      )
    }
    setBusy(false)
  }
  const disable = async () => {
    setBusy(true)
    const sub = await currentSubscription()
    if (sub) {
      await unsubscribePush(sub.endpoint).catch(() => undefined)
      await sub.unsubscribe().catch(() => undefined)
    }
    setSubscribed(false)
    setBusy(false)
    reminders.refetch()
  }
  const test = async () => {
    setMessage('')
    try {
      const r = await testPush()
      setMessage(r.sent ? 'Sent — it should arrive in a few seconds.' : 'Nothing was delivered. Turn notifications off and on again on this device.')
    } catch (error) {
      setMessage(errorText(error, 'Could not send a test.'))
    }
  }

  return (
    <div className="stack">
      <section className="card stack">
        <CardHead
          title="This device"
          aside={subscribed ? <Pill topic="ok">On</Pill> : <Pill>Off</Pill>}
          sub={data.subscriptions ? `${data.subscriptions} ${data.subscriptions === 1 ? 'device' : 'devices'} get reminders` : 'No device gets reminders yet'}
        />
        {iosBlocked && (
          <p className="notice small">{data.ios_note || 'On iPhone, add RunCoach to your Home Screen first (Share → Add to Home Screen), then open it from there to turn on reminders.'}</p>
        )}
        {!pushSupported() && !iosBlocked && <p className="muted small">This browser can’t receive push notifications.</p>}
        <div className="row-wrap">
          {subscribed ? (
            <>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={test}>Send a test</button>
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={disable}>Turn off here</button>
            </>
          ) : (
            <button type="button" className="btn btn-primary" disabled={busy || iosBlocked || !pushSupported()} onClick={enable}>
              {busy ? 'Turning on…' : 'Allow notifications'}
            </button>
          )}
        </div>
        {message && <p className="small">{message}</p>}
      </section>

      <section className="card">
        <CardHead title="Reminders" sub="Sent at your local time. Notifications never include health numbers or habit counts." />
        {data.reminders.map((r) => (
          <ReminderRow key={r.key} r={r} disabled={false} onPatch={(p) => patch.mutate({ [r.key]: p })} />
        ))}
        {patch.isError && <p className="bad small">{errorText(patch.error, 'Could not save that.')}</p>}
      </section>

      <AlarmRemindersCard />

      {data.nudges && data.nudges.length > 0 && (
        <NudgesCard data={data} onPatch={(p) => patch.mutate(p)} />
      )}
    </div>
  )
}

const asOfText = (iso: string | null | undefined) => {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const sameDay = d.toDateString() === new Date().toDateString()
  return sameDay
    ? d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })
}

const NUDGE_NOTE: Record<string, string> = {
  move: 'When you’ve been still for a while. Never during or just after a run.',
  breathing: 'When stress stays high for 30+ minutes. Opens the breathing guide.',
  water: 'A gentle reminder, skipped when you’ve just logged water or hit your target.',
}

/** R11 §C: move / breathing / water nudges — off by default, within your hours. */
function NudgesCard({ data, onPatch }: { data: RemindersResponse; onPatch: (p: Record<string, object>) => void }) {
  const asOf = asOfText(data.data_as_of)
  const q = data.quiet_hours
  return (
    <section className="card">
      <CardHead
        title="Through the day"
        sub={`Based on your watch’s last sync${asOf ? ` (${asOf})` : ''} — Garmin data can lag, so a nudge may come a little late. Never during quiet hours.`}
      />
      {data.nudges!.map((n) => <NudgeRow key={n.key} n={n} onPatch={(p) => onPatch({ [n.key]: p })} />)}
      {q && (
        <>
          <div className="reminder-row">
            <span className="grow">
              <strong>Quiet hours</strong>
              <span className="muted small block">No nudges between these times.</span>
            </span>
          </div>
          <div className="reminder-extra">
            <label>From <TimeInput label="Quiet hours start" value={q.start} onSave={(start) => onPatch({ quiet_hours: { start } })} /></label>
            <label>to <TimeInput label="Quiet hours end" value={q.end} onSave={(end) => onPatch({ quiet_hours: { end } })} /></label>
          </div>
        </>
      )}
    </section>
  )
}

function TimeInput({ label, value, onSave, disabled }: { label: string; value: string; onSave: (v: string) => void; disabled?: boolean }) {
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  return (
    <input
      type="time"
      aria-label={label}
      value={v}
      disabled={disabled}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => v && v !== value && onSave(v)}
    />
  )
}

function NumberSelect({ label, value, options, format, onSave }: { label: string; value: number; options: number[]; format: (v: number) => string; onSave: (v: number) => void }) {
  const list = options.includes(value) ? options : [...options, value].sort((a, b) => a - b)
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onSave(Number(e.target.value))}>
        {list.map((o) => <option key={o} value={o}>{format(o)}</option>)}
      </select>
    </label>
  )
}

function NudgeRow({ n, onPatch }: { n: Nudge; onPatch: (p: Partial<Nudge>) => void }) {
  return (
    <>
      <div className="reminder-row">
        <span className="grow">
          <strong>{n.label}</strong>
          <span className="muted small block">{n.description || NUDGE_NOTE[n.key]}</span>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={n.enabled}
          aria-label={n.label}
          className={`switch ${n.enabled ? 'is-on' : ''}`}
          onClick={() => onPatch({ enabled: !n.enabled })}
        />
      </div>
      {n.enabled && (
        <div className="reminder-extra">
          <label>From <TimeInput label={`${n.label} from`} value={n.start} onSave={(start) => onPatch({ start })} /></label>
          <label>to <TimeInput label={`${n.label} until`} value={n.end} onSave={(end) => onPatch({ end })} /></label>
          {n.key === 'move' && n.after_min != null && (
            <NumberSelect label="After" value={n.after_min} options={[60, 75, 90]} format={(v) => `${v} min still`} onSave={(after_min) => onPatch({ after_min })} />
          )}
          {n.key === 'breathing' && n.threshold != null && (
            <NumberSelect label="Stress" value={n.threshold} options={[51, 60, 70, 76, 90]} format={(v) => `${v}+`} onSave={(threshold) => onPatch({ threshold })} />
          )}
          {n.key === 'water' && n.every_h != null && (
            <NumberSelect label="Every" value={n.every_h} options={[1, 2, 3, 4]} format={(v) => `${v} h`} onSave={(every_h) => onPatch({ every_h })} />
          )}
          <NumberSelect label="Max" value={n.max_per_day} options={[1, 2, 3, 4, 5, 6, 7, 8]} format={(v) => `${v} a day`} onSave={(max_per_day) => onPatch({ max_per_day })} />
        </div>
      )}
    </>
  )
}

export function RemindersTeaser() {
  const reminders = useReminders()
  const d = reminders.data
  if (!d || !d.available) return null
  const on = [...d.reminders, ...(d.nudges ?? [])].filter((r) => r.enabled)
  return (
    <Link to="/me/reminders" className="card link-row">
      <span className="link-row-icon"><BellIcon /></span>
      <span className="grow">
        <span className="link-row-title">Reminders</span>
        <span className="link-row-text">{on.length ? on.map((r) => r.label).join(' · ') : 'Morning check-in, habit log, move, breathing, water, weekly report'}</span>
      </span>
      <ChevronRight size={18} className="muted" />
    </Link>
  )
}
