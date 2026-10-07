import { useState } from 'react'
import { errorText } from '../../lib/queries'
import { useCalendarFeed, useCalendarFeedActions } from '../../lib/r14'
import { CalendarIcon } from '../Icons'
import { CardHead } from '../Kit'
import { Empty, ErrorState, Skeleton } from '../States'

/**
 * R14 §5 Me → Calendar sync: a private subscribe link (ICS) for planned runs, strength
 * and races. Add to Google / Apple, copy the link, or regenerate / turn off (each with
 * an in-page confirm — the old link stops working at once).
 */
export function CalendarSync() {
  const feed = useCalendarFeed()
  const { create, revoke } = useCalendarFeedActions()
  const [confirm, setConfirm] = useState<'' | 'regenerate' | 'revoke'>('')
  const [copied, setCopied] = useState(false)
  const f = feed.data

  if (feed.isPending) return <section className="card"><Skeleton lines={4} /></section>
  if (feed.isError) return <ErrorState message={errorText(feed.error, 'Calendar sync did not load.')} onRetry={() => feed.refetch()} />
  if (f === null) return <Empty title="Calendar sync isn’t available yet">Check back after the next update.</Empty>

  const url = f?.url ?? (f?.path ? `${window.location.origin}${f.path}` : null)
  const webcal = f?.webcal_url ?? (url ? url.replace(/^https?:\/\//, 'webcal://') : null)
  const google = f?.google_url ?? (webcal ? `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcal)}` : null)
  const busy = create.isPending || revoke.isPending
  const error = create.error ?? revoke.error

  const copy = async () => {
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      /* clipboard blocked: the link is selectable on screen */
    }
  }

  if (!f?.enabled || !url) {
    return (
      <section className="card stack-sm">
        <CardHead title={<span className="row-inline"><CalendarIcon size={20} /> See your plan in your calendar</span>} />
        <p className="small">Planned runs, strength sessions and races show up in Google or Apple Calendar and update when the plan changes. Only workout titles and steps — no health data.</p>
        {error && <p className="bad small">{errorText(error, 'Could not turn it on.')}</p>}
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => create.mutate()}>
          {create.isPending ? 'Creating…' : 'Create my calendar link'}
        </button>
      </section>
    )
  }

  return (
    <div className="stack">
      <section className="card stack-sm">
        <CardHead title="Add to your calendar" sub="It refreshes on its own — usually within a few hours of a plan change." />
        {google && <a className="btn btn-primary btn-block" href={google} target="_blank" rel="noreferrer">Add to Google Calendar</a>}
        {webcal && <a className="btn btn-secondary btn-block" href={webcal}>Add to Apple Calendar</a>}
      </section>

      <section className="card stack-sm">
        <span className="lbl">Your private link</span>
        <input readOnly className="mono small" value={url} aria-label="Calendar subscribe link" onFocus={(e) => e.currentTarget.select()} />
        <button type="button" className="btn btn-secondary btn-sm" onClick={copy}>{copied ? 'Copied' : 'Copy link'}</button>
        <p className="muted small">Anyone with this link can see your planned workouts. Don’t post it publicly.</p>
        {f.last_fetched_at && <p className="muted small">Last read by a calendar: {new Date(f.last_fetched_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</p>}
      </section>

      <section className="card stack-sm">
        <CardHead title="How to" />
        <ul className="bullets small">
          <li><b>Google (on a computer):</b> tap “Add to Google Calendar”, then Add. Or Settings → Add calendar → From URL, paste the link.</li>
          <li><b>iPhone / Mac:</b> tap “Add to Apple Calendar” and Subscribe. Or Settings → Calendar → Accounts → Add subscribed calendar.</li>
          <li><b>Outlook:</b> Add calendar → Subscribe from web, paste the link.</li>
        </ul>
      </section>

      <section className="card stack-sm">
        {confirm ? (
          <div className="stack-sm">
            <p className="small">
              {confirm === 'regenerate'
                ? 'Make a new link? The old one stops working right away — re-add the calendar with the new link.'
                : 'Turn off calendar sync? The link stops working and the calendar stops updating.'}
            </p>
            <div className="row-wrap">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm('')}>Cancel</button>
              <button
                type="button"
                className="btn btn-danger btn-sm"
                disabled={busy}
                onClick={() => (confirm === 'regenerate' ? create : revoke).mutate(undefined, { onSuccess: () => setConfirm('') })}
              >
                {confirm === 'regenerate' ? 'Make a new link' : 'Turn off'}
              </button>
            </div>
          </div>
        ) : (
          <div className="row-wrap">
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setConfirm('regenerate')}>New link…</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm('revoke')}>Turn off…</button>
          </div>
        )}
        {error && <p className="bad small">{errorText(error, 'Could not change it.')}</p>}
      </section>
    </div>
  )
}
