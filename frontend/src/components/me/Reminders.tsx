import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { currentSubscription, isIOS, isStandalone, pushSupported, subscribe } from '../../lib/push'
import { errorText, subscribePush, testPush, unsubscribePush, usePatchReminders, useReminders } from '../../lib/queries'
import type { Reminder } from '../../lib/types'
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
    return <Empty icon={<BellIcon size={32} />} title="Reminders aren’t switched on here">Push notifications aren’t set up on this server yet.</Empty>
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
    </div>
  )
}

export function RemindersTeaser() {
  const reminders = useReminders()
  const d = reminders.data
  if (!d || !d.available) return null
  const on = d.reminders.filter((r) => r.enabled)
  return (
    <Link to="/me/reminders" className="card link-row">
      <span className="link-row-icon"><BellIcon /></span>
      <span className="grow">
        <span className="link-row-title">Reminders</span>
        <span className="link-row-text">{on.length ? on.map((r) => r.label).join(' · ') : 'Morning check-in, habit log, best time to run, weekly report'}</span>
      </span>
      <ChevronRight size={18} className="muted" />
    </Link>
  )
}
