import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { addDays, dur, parseDate, todayISO } from '../../lib/format'
import { errorText, usePatchAlarm, useMyAlarm, useWakePlan, useWatchAlarms } from '../../lib/queries'
import type { MyAlarm, WakeFlag, WakePlan, WatchAlarms } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { Field } from '../Field'
import { AlarmIcon, ChevronRight, WatchIcon } from '../Icons'
import { CardHead, Pill } from '../Kit'
import {
  DAY_LETTER, DAY_SHORT, alarmClock, alarmIntent, daysText, isEvening, parseTime, platform,
} from './alarmUtil'

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]

function dayLabel(iso: string): string {
  const today = todayISO()
  const d = parseDate(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  if (iso === today) return `Today, ${d}`
  if (iso === addDays(today, 1)) return `Tomorrow, ${d}`
  return d
}

function whyText(p: WakePlan): string | null {
  if (p.sentence) return p.sentence
  const run = p.run
  if (p.wake_source === 'run' && run?.run_time) return `Your run is at ${alarmClock(run.run_time)} — wake 45 min before.`
  if (p.wake_source === 'habit') return 'Your usual wake time over the last week.'
  if (p.wake_source === 'default') return 'No run time or sleep history yet, so 7:00 is a starting point.'
  return null
}

/** Mismatch / missing-alarm warnings ("Your run is at 6:30 but your watch alarm is 7:00"). */
export function AlarmFlags({ flags }: { flags: WakeFlag[] | null | undefined }) {
  if (!flags?.length) return null
  return (
    <div role="list" aria-label="Alarm warnings">
      {flags.map((f) => (
        <p key={f.kind + f.text} className={`alarm-warn ${f.kind === 'no_watch_alarm_for_run' ? 'is-info' : ''}`} role="listitem">
          <i aria-hidden="true">!</i>
          <span>{f.text}</span>
        </p>
      ))}
    </div>
  )
}

/** "Set alarm on phone": Android opens Clock with the time filled in; iOS gets the steps. */
function PhoneAlarm({ time }: { time: string }) {
  const [iosOpen, setIosOpen] = useState(false)
  const os = platform()
  const intent = alarmIntent(time)
  if (os === 'android' && intent) {
    return (
      <button type="button" className="btn btn-primary" onClick={() => { window.location.href = intent }}>
        <AlarmIcon size={18} /> Set alarm on phone
      </button>
    )
  }
  if (os === 'ios') {
    return (
      <>
        <button type="button" className="btn btn-primary" aria-expanded={iosOpen} onClick={() => setIosOpen((v) => !v)}>
          <AlarmIcon size={18} /> Set alarm on phone
        </button>
        {iosOpen && (
          <p className="ios-clock-note" role="status" style={{ flexBasis: '100%' }}>
            Set <b>{alarmClock(time)}</b> in the Clock app: <strong>Open Clock → Alarm → +</strong>. iPhone doesn’t let web apps set alarms.
          </p>
        )}
      </>
    )
  }
  return null
}

/**
 * R12 §B1 Wake planner: tomorrow's wake time (from the run time / plan, else your usual
 * wake) and bedtime (wake − need − 15 min); save as "my alarm", set it on the phone.
 * `variant="today"` is the compact evening card on Today.
 */
export function WakePlannerCard({ variant = 'full' }: { variant?: 'full' | 'today' }) {
  const plan = useWakePlan()
  const alarm = useMyAlarm()
  const [saving, setSaving] = useState(false)
  const p = plan.data
  if (!p || !p.wake_time) return null
  const today = variant === 'today'
  const mine = p.my_alarm ?? alarm.data ?? null
  const why = whyText(p)
  const os = platform()

  return (
    <section className={`card wake-card ${today ? 'is-today' : ''}`} aria-labelledby="wake-title">
      <CardHead
        title={<span id="wake-title">{today ? 'Tonight → tomorrow' : 'Wake planner'}</span>}
        sub={dayLabel(p.date)}
        aside={p.run?.planned ? <Pill topic="run">{p.run.title || 'Run day'}</Pill> : undefined}
      />
      <div className="wake-times">
        {p.bedtime && (
          <div className="wake-time">
            <span className="lbl">In bed by</span>
            <b>{alarmClock(p.bedtime)}</b>
            {p.need_s ? <span className="muted small">{dur(p.need_s)} sleep{p.need_source === 'garmin' ? ' (Garmin)' : p.need_source === 'athlete' || p.need_source === 'user' ? ' (set by you)' : ''} + 15 min</span> : null}
          </div>
        )}
        <div className="wake-time is-wake">
          <span className="lbl">Wake at</span>
          <b>{alarmClock(p.wake_time)}</b>
          {p.run?.run_time && p.wake_source === 'run' ? <span className="muted small">run at {alarmClock(p.run.run_time)}</span> : null}
        </div>
      </div>
      {why && <p className="wake-why">{why}</p>}
      <AlarmFlags flags={today ? p.flags?.slice(0, 1) : p.flags} />

      <div className="wake-actions">
        <PhoneAlarm time={p.wake_time} />
        <button type="button" className={`btn ${os === 'other' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setSaving(true)}>
          Save as my alarm
        </button>
      </div>
      {os === 'other' && !today && (
        <p className="muted small" style={{ marginTop: 8 }}>On Android, “Set alarm on phone” opens your Clock app with this time. On iPhone you set it in Clock yourself.</p>
      )}

      {mine?.enabled && mine.time && (
        <div className="my-alarm-row">
          <AlarmIcon size={20} className="muted" />
          <span className="grow">
            <strong className="block">My alarm {alarmClock(mine.time)}</strong>
            <span className="muted small">{daysText(mine.days)}{mine.push ? ' · with a notification' : ''}</span>
          </span>
          <Link to="/me/reminders" className="btn btn-ghost btn-sm" aria-label="Alarm settings">Edit</Link>
        </div>
      )}

      <SaveAlarmSheet open={saving} onClose={() => setSaving(false)} time={p.wake_time} alarm={mine} weekday={p.weekday} />
    </section>
  )
}

/** Today's evening card: the planner after 6 pm, re-checked every few minutes. */
export function EveningWakeCard() {
  const [evening, setEvening] = useState(() => isEvening())
  useEffect(() => {
    const t = setInterval(() => setEvening(isEvening()), 5 * 60_000)
    return () => clearInterval(t)
  }, [])
  return evening ? <WakePlannerCard variant="today" /> : null
}

export function DayPicker7({ value, onChange, label = 'Days' }: { value: number[]; onChange: (d: number[]) => void; label?: string }) {
  const toggle = (d: number) => onChange(value.includes(d) ? value.filter((x) => x !== d) : [...value, d].sort((a, b) => a - b))
  return (
    <div className="day-pick" role="group" aria-label={label}>
      {ALL_DAYS.map((d) => (
        <button key={d} type="button" aria-pressed={value.includes(d)} aria-label={DAY_SHORT[d]} onClick={() => toggle(d)}>
          {DAY_LETTER[d]}
        </button>
      ))}
    </div>
  )
}

/** "Save as my alarm": time + days (+ optional notification) stored in RunCoach. */
function SaveAlarmSheet({
  open, onClose, time, alarm, weekday,
}: { open: boolean; onClose: () => void; time: string; alarm: MyAlarm | null; weekday: number }) {
  const patch = usePatchAlarm()
  const [t, setT] = useState(time)
  const [days, setDays] = useState<number[]>(ALL_DAYS)
  const [push, setPush] = useState(false)
  const [wasOpen, setWasOpen] = useState(false)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setT(time)
      setDays(alarm?.days?.length ? alarm.days : ALL_DAYS.includes(weekday) ? ALL_DAYS : [0, 1, 2, 3, 4])
      setPush(alarm?.push ?? false)
      patch.reset()
    }
  }
  const error = !parseTime(t) ? 'Pick a time.' : !days.length ? 'Pick at least one day.' : null
  const canPush = alarm?.push_available !== false
  const save = () => {
    if (error) return
    patch.mutate({ time: t, days, enabled: true, push: canPush && push }, { onSuccess: onClose })
  }
  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      title="My alarm"
      footer={<button type="button" className="btn btn-primary grow" disabled={!!error || patch.isPending} onClick={save}>{patch.isPending ? 'Saving…' : 'Save alarm'}</button>}
    >
      <div className="stack">
        <Field label="Time">
          <input className="alarm-time-input" type="time" value={t} onChange={(e) => setT(e.target.value)} />
        </Field>
        <div>
          <span className="field-label">Days · {daysText(days)}</span>
          <DayPicker7 value={days} onChange={setDays} />
        </div>
        <div className="switch-row">
          <span className="grow">
            <strong>Notify me at this time</strong>
            <span className="muted small block">A push notification, <b>not a real alarm</b> — it won’t ring through silent mode. Set the phone alarm too.</span>
            {!canPush && <span className="muted small block">Notifications aren’t set up on this server.</span>}
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={push && canPush}
            aria-label="Notification at the alarm time"
            disabled={!canPush}
            className={`switch ${push && canPush ? 'is-on' : ''}`}
            onClick={() => setPush((v) => !v)}
          />
        </div>
        {alarm?.note && <p className="muted small">{alarm.note}</p>}
        {error && <p className="field-error">{error}</p>}
        {patch.isError && <p className="field-error">{errorText(patch.error, 'Could not save the alarm.')}</p>}
      </div>
    </BottomSheet>
  )
}

/**
 * R12 §B4 Watch alarm check (read-only): the alarms on your Garmin, plus warnings when
 * they don't fit tomorrow's run. Hidden when the watch can't be read.
 */
export function WatchAlarmsCard({ link = false, showFlags = true }: { link?: boolean; showFlags?: boolean }) {
  const q = useWatchAlarms()
  const plan = useWakePlan()
  const w: WatchAlarms | null | undefined = q.data ?? plan.data?.watch
  if (!w || !w.available) return null
  const flags = !showFlags ? [] : (plan.data?.flags ?? []).filter((f) => f.kind.startsWith('watch') || f.kind === 'no_watch_alarm_for_run')
  const alarms = w.alarms ?? []
  return (
    <section className="card">
      <CardHead
        title={<span className="row-inline"><WatchIcon size={20} /> Watch alarms</span>}
        sub={w.checked_on ? `Read from Garmin · ${parseDate(w.checked_on).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}` : 'Read from Garmin'}
      />
      {alarms.length ? (
        <ul className="watch-alarms">
          {alarms.map((a, i) => (
            <li key={`${a.time}-${i}`} className={a.enabled ? '' : 'is-off'}>
              <b>{alarmClock(a.time)}</b>
              <span className="grow">
                <span className="block">{daysText(a.days, a.once)}{a.enabled ? '' : ' · off'}</span>
                {(a.label || a.device) && <span className="muted small">{[a.label, a.device].filter(Boolean).join(' · ')}</span>}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">No alarms set on your watch.</p>
      )}
      <AlarmFlags flags={flags} />
      <p className="chart-caption" style={{ marginTop: 8 }}>
        RunCoach only reads these — change them on the watch or in Garmin Connect.
        {link && <> <Link to="/health/sleep">Wake planner <ChevronRight size={14} /></Link></>}
      </p>
    </section>
  )
}

const LEADS = [15, 30, 45, 60, 90, 120]

/**
 * Me → Reminders: my alarm, its notification, the bedtime wind-down and the usual run
 * time. Clearly a notification, not a real alarm.
 */
export function AlarmRemindersCard() {
  const q = useMyAlarm()
  const patch = usePatchAlarm()
  const a = q.data
  const [runTime, setRunTime] = useState(a?.run_time ?? '')
  const [time, setTime] = useState(a?.time ?? '')
  useEffect(() => setRunTime(a?.run_time ?? ''), [a?.run_time])
  useEffect(() => setTime(a?.time ?? ''), [a?.time])
  if (!a) return null
  const canPush = a.push_available
  const save = (p: Parameters<typeof patch.mutate>[0]) => patch.mutate(p)

  return (
    <section className="card">
      <CardHead title={<span className="row-inline"><AlarmIcon size={20} /> Alarm &amp; bedtime</span>} sub="Plans tomorrow’s wake time and bedtime around your run." />

      <div className="reminder-row">
        <span className="grow">
          <strong>My alarm</strong>
          <span className="muted small block">{a.time ? daysText(a.days) : 'Not set — pick a time or save one from Health → Sleep.'}</span>
        </span>
        <input
          type="time"
          aria-label="My alarm time"
          value={time}
          onChange={(e) => setTime(e.target.value)}
          onBlur={() => time && time !== a.time && save({ time })}
        />
        <button
          type="button"
          role="switch"
          aria-checked={a.enabled}
          aria-label="My alarm on"
          disabled={!a.time && !time}
          className={`switch ${a.enabled ? 'is-on' : ''}`}
          onClick={() => save(a.enabled ? { enabled: false } : { enabled: true, time: time || a.time, days: a.days?.length ? a.days : ALL_DAYS })}
        />
      </div>
      {a.enabled && (
        <div className="reminder-extra" style={{ display: 'block' }}>
          <DayPicker7 value={a.days ?? []} onChange={(days) => days.length && save({ days })} label="Alarm days" />
        </div>
      )}

      <div className="reminder-row">
        <span className="grow">
          <strong>Alarm notification</strong>
          <span className="muted small block">A push at your alarm time.</span>
          <span className="reminder-label-note">Notification, not a real alarm — it won’t ring in silent mode.</span>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={a.push}
          aria-label="Alarm notification (not a real alarm)"
          disabled={!canPush || !a.enabled}
          className={`switch ${a.push ? 'is-on' : ''}`}
          onClick={() => save({ push: !a.push })}
        />
      </div>

      <div className="reminder-row">
        <span className="grow">
          <strong>Bedtime reminder</strong>
          <span className="muted small block">A wind-down push {a.bedtime_lead_min} min before tomorrow’s planned bedtime.</span>
          <span className="reminder-label-note">Notification, not an alarm.</span>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={a.bedtime_reminder}
          aria-label="Bedtime reminder"
          disabled={!canPush}
          className={`switch ${a.bedtime_reminder ? 'is-on' : ''}`}
          onClick={() => save({ bedtime_reminder: !a.bedtime_reminder })}
        />
      </div>
      {a.bedtime_reminder && (
        <div className="reminder-extra">
          <label>
            Remind me
            <select value={a.bedtime_lead_min} onChange={(e) => save({ bedtime_lead_min: Number(e.target.value) })}>
              {(LEADS.includes(a.bedtime_lead_min) ? LEADS : [...LEADS, a.bedtime_lead_min].sort((x, y) => x - y)).map((m) => (
                <option key={m} value={m}>{m} min before</option>
              ))}
            </select>
          </label>
        </div>
      )}

      <div className="reminder-row">
        <span className="grow">
          <strong>I usually run at</strong>
          <span className="muted small block">Wake time = 45 min before this on run days. Empty = learnt from your runs.</span>
        </span>
        <input
          type="time"
          aria-label="Usual run time"
          value={runTime}
          onChange={(e) => setRunTime(e.target.value)}
          onBlur={() => (runTime || null) !== a.run_time && save({ run_time: runTime || null })}
        />
      </div>

      {!canPush && <p className="muted small" style={{ marginTop: 8 }}>Notifications aren’t set up on this server, so only the planner works.</p>}
      {a.note && <p className="chart-caption" style={{ marginTop: 8 }}>{a.note}</p>}
      {patch.isError && <p className="bad small">{errorText(patch.error, 'Could not save that.')}</p>}
    </section>
  )
}
