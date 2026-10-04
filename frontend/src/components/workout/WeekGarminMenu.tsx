import { useQueryClient, type InfiniteData } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { monthDay, parseDate } from '../../lib/format'
import { errorText, useSendDaysToGarmin } from '../../lib/queries'
import type { CalendarResponse, CalWeek, GarminSendResult } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { CheckIcon, MoreVIcon } from '../Icons'
import { Loading } from '../States'

const STATUS: Record<string, string> = {
  uploaded: 'Sent', updated: 'Updated on watch', unchanged: 'Already on watch', removed: 'Removed',
  skipped: 'Not sent', error: 'Failed',
}

/** Days from today through the week's Sunday — what POST /plans/active/garmin/ takes. */
const daysLeft = (today: string, end: string) =>
  Math.round((parseDate(end).getTime() - parseDate(today).getTime()) / 86_400_000) + 1

/** Week header ⋮ → "Send this week to Garmin", then the per-workout results. */
export function WeekGarminMenu({ week, today }: { week: CalWeek; today: string }) {
  const send = useSendDaysToGarmin()
  const [menu, setMenu] = useState(false)
  const [sheet, setSheet] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const days = daysLeft(today, week.end)

  useEffect(() => {
    if (!menu) return
    const away = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setMenu(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [menu])

  if (days < 1) return null
  const current = week.start <= today
  return (
    <div className="menu-wrap" ref={wrap}>
      <button type="button" className="icon-btn" aria-label="Week options" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>
        <MoreVIcon />
      </button>
      {menu && (
        <div className="menu" role="menu">
          <button
            type="button" role="menuitem"
            onClick={() => { setMenu(false); setSheet(true); send.mutate(days) }}
          >
            {current ? 'Send this week to Garmin' : `Send through ${monthDay(week.end)} to Garmin`}
          </button>
        </div>
      )}
      <BottomSheet open={sheet} onClose={() => { setSheet(false); send.reset() }} title="Send to Garmin" label="Send to Garmin">
        {send.isPending && <Loading label="Sending workouts to your watch…" />}
        {send.isError && <p className="bad">{errorText(send.error, 'Garmin did not accept the upload. Nothing was changed.')}</p>}
        {send.isSuccess && <SendResults results={send.data} />}
      </BottomSheet>
    </div>
  )
}

/** Results carry ids and dates only; titles come from the loaded calendar. */
function useWorkoutTitles(): Map<number, string> {
  const client = useQueryClient()
  const titles = new Map<number, string>()
  const cal = client.getQueryData<InfiniteData<CalendarResponse>>(['calendar'])
  for (const page of cal?.pages ?? []) {
    for (const day of page.days) {
      for (const item of day.items) if (item.type === 'workout') titles.set(item.workout.id, item.workout.title)
    }
  }
  return titles
}

function SendResults({ results }: { results: GarminSendResult[] }) {
  const titles = useWorkoutTitles()
  if (!results.length) return <p className="muted">No planned runs left this week to send.</p>
  const failed = results.filter((r) => r.status === 'error').length
  return (
    <>
      <p className={failed ? 'bad' : 'muted'}>
        {failed ? `${failed} of ${results.length} did not go through.` : 'All set — they’re on your watch calendar.'}
      </p>
      <ul className="send-results">
        {results.map((r) => (
          <li key={r.workout_id} className={`send-result is-${r.status === 'error' ? 'error' : 'ok'}`}>
            <span className="send-mark" aria-hidden="true">{r.status === 'error' ? '!' : <CheckIcon size={14} />}</span>
            <div className="grow">
              <p className="send-title">{r.title ?? titles.get(r.workout_id) ?? 'Workout'}</p>
              <p className="muted small">
                {r.date ? `${monthDay(r.date)} · ` : ''}{STATUS[r.status] ?? r.status}
                {r.detail ? ` — ${r.detail}` : ''}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}
