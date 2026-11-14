/**
 * Start the plan over.
 *
 * The endpoint for this has existed since the gym work went in and nothing in
 * the app ever called it, so a plan you had changed your mind about could only
 * be unpicked one workout at a time — and nobody does that for sixteen weeks
 * of them.
 *
 * The server's rules are the screen's rules, deliberately:
 *
 *   Nothing is one button. Clearing an unaccepted proposal is a weekly thing;
 *   deleting every run you have ever recorded is not, and the two must not sit
 *   one tap apart. Each target is ticked on its own and the list is ordered
 *   from the routine to the irreversible.
 *
 *   What happened is not planning data. Your runs are the record of your life,
 *   not of a plan. Clearing them is offered because you might genuinely want
 *   it, and it is the only row that says it cannot be undone from in here.
 *
 *   A watch is not a database. Anything already pushed to Garmin is taken off
 *   it, and the count comes back so the screen can say so rather than leaving
 *   weeks of ghost workouts scheduled on your wrist.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../../lib/auth'
import { errorText, invalidatePlanData } from '../../lib/queries'
import { InfoButton } from '../health/InfoButton'

type Target = {
  key: 'upcoming' | 'plans' | 'strength' | 'adjustments' | 'races'
  title: string
  sub: string
}

/** Only what the coach planned.
 *
 * The endpoint can also delete every activity on record, and this screen does
 * not offer it. Clearing a plan and deleting your training history are not two
 * settings of one control — one is a weekly act of re-planning, the other
 * throws away the only thing the re-planning is based on. The second belongs
 * with the other account-level deletions, not one tick away from the first. */
const TARGETS: Target[] = [
  {
    key: 'upcoming',
    title: 'Everything still to come',
    sub: 'Clears the active plan from today onward and leaves what you have already done. This is the one you want to re-plan from here.',
  },
  {
    key: 'strength',
    title: 'Gym sessions',
    sub: 'Every planned strength day from today on. Your rungs are kept — you do not start back at wall push-ups.',
  },
  {
    key: 'plans',
    title: 'Every plan',
    sub: 'Including finished ones and proposals you never accepted.',
  },
  {
    key: 'adjustments',
    title: 'Plan adjustments',
    sub: 'The record of what the coach changed and why.',
  },
  {
    key: 'races',
    title: 'Races',
    sub: 'Every race you have entered, target or not.',
  },
]

const LABEL: Record<string, string> = {
  workouts: 'planned runs',
  strength: 'gym sessions',
  plans: 'plans',
  adjustments: 'adjustments',
  races: 'races',
  removed_from_watch: 'taken off your watch',
}

/**
 * Pull the whole history down again.
 *
 * Its own step, after the clearing, because the order is the point: a plan
 * rebuilt from a half-empty history is a plan built on a hole. A normal sync
 * stops at the newest run it already holds, which is useless when the gap is
 * in the middle — exactly what a spell with Garmin disconnected leaves behind.
 * This one asks for the full twelve months.
 *
 * It fills gaps and repairs nothing. A run already stored comes back
 * untouched, per-second data and all, because activities are idempotent on
 * their Garmin id.
 */
function Resync() {
  const client = useQueryClient()
  const [started, setStarted] = useState(false)

  const resync = useMutation({
    mutationFn: () =>
      api<{ job_id?: string; deduped?: boolean }>('/garmin/sync/', {
        method: 'POST',
        ...json({ full: true, rebackfill: true }),
      }),
    onSuccess: () => {
      setStarted(true)
      client.invalidateQueries({ queryKey: ['sync-status'] })
      client.invalidateQueries({ queryKey: ['activities'] })
    },
  })

  return (
    <section className="card stack">
      <div className="row">
        <strong>Then fetch everything again</strong>
      </div>
      <p className="muted small reset-sub">
        Asks Garmin for the last twelve months rather than stopping at your most
        recent run. Worth doing after clearing, so a new plan is built on a full
        history instead of a gap.
      </p>
      <button
        type="button"
        className="btn btn-secondary btn-grow"
        disabled={resync.isPending}
        onClick={() => { setStarted(false); resync.mutate() }}
      >
        {resync.isPending ? 'Starting…' : 'Re-sync everything from Garmin'}
      </button>
      {started && (
        <p className="small muted" role="status">
          Running in the background — it takes a few minutes. Runs already stored
          are left alone; this fills in the ones that are missing.
        </p>
      )}
      {resync.error && (
        <p className="small bad" role="alert">
          {errorText(resync.error, 'Could not start the sync.')}
        </p>
      )}
    </section>
  )
}

export function ResetPlanning() {
  return (
    <>
      <Rebuild />
      <ClearPlanning />
      <Resync />
    </>
  )
}

/**
 * Rebuild the active plan rather than throwing it away.
 *
 * First on this screen because it is almost always the right answer and
 * clearing almost never is. Saving new training days already reflows the
 * plan — sessions move to the days you picked, keeping the weekly total. This
 * is the heavier version: regenerate the remaining weeks from where you
 * actually are now, which is what a plan written before a month off needs.
 *
 * Your history is untouched either way. Only the weeks ahead change.
 */
function Rebuild() {
  const client = useQueryClient()
  const [done, setDone] = useState(false)

  const rebuild = useMutation({
    mutationFn: () => api('/plans/active/rebuild/', { method: 'POST' }),
    onSuccess: () => {
      setDone(true)
      invalidatePlanData(client)
      client.invalidateQueries({ queryKey: ['strength'] })
    },
  })

  return (
    <section className="card stack">
      <div className="row">
        <strong>Rebuild the plan</strong>
      </div>
      <p className="muted small reset-sub">
        Keeps the plan and rewrites the weeks ahead from where you are now.
        What you have already done stays exactly as it is. Try this before
        clearing anything — a plan written before a month off needs rebuilding,
        not deleting.
      </p>
      <button
        type="button"
        className="btn btn-primary btn-grow"
        disabled={rebuild.isPending}
        onClick={() => { setDone(false); rebuild.mutate() }}
      >
        {rebuild.isPending ? 'Rebuilding…' : 'Rebuild from where I am now'}
      </button>
      {done && (
        <p className="small muted" role="status">
          Rebuilt. Have a look at the Plan tab.
        </p>
      )}
      {rebuild.error && (
        <div className="reset-dead-end" role="alert">
          <p className="small bad">
            {errorText(rebuild.error, 'The plan could not be rebuilt.')}
          </p>
          {/* The commonest way to see this is to clear everything and then
              press rebuild, which is a dead end: there is nothing to rebuild
              and the screen has to say what to do instead.

              Setting a goal leads, because "ask the coach" was the only answer
              here and it is the one that failed — the planner's dated-goal
              mode could only be reached by saying the right thing in chat, and
              it could not express a distance you mean to cover with walk
              breaks at all. */}
          <Link to="/me/goal" className="btn btn-primary btn-grow">
            Set a goal — a distance by a date
          </Link>
          <Link to="/chat/new" className="btn btn-secondary btn-grow">
            Or ask the coach for a new plan
          </Link>
        </div>
      )}
    </section>
  )
}

function ClearPlanning() {
  const client = useQueryClient()
  const [picked, setPicked] = useState<Set<Target['key']>>(new Set())
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState<Record<string, number> | null>(null)

  const reset = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ cleared: Record<string, number> }>('/plans/reset/', { method: 'POST', ...json(body) }),
    onSuccess: (result) => {
      setDone(result.cleared)
      setPicked(new Set())
      setConfirm('')
      invalidatePlanData(client)
      client.invalidateQueries({ queryKey: ['strength'] })
      client.invalidateQueries({ queryKey: ['activities'] })
    },
  })

  const toggle = (key: Target['key']) => {
    setDone(null)
    setPicked((was) => {
      const next = new Set(was)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const nothing = picked.size === 0
  const ready = !nothing && confirm.trim().toUpperCase() === 'CLEAR'

  return (
    <section className="card stack reset">
      <div className="row">
        <strong>Clear data</strong>
        <InfoButton title="Starting over">
          <p>
            Plans are stored, not recalculated, which is what makes them
            editable — and what makes a wrong one stick. This is how you unpick
            one without editing sixteen weeks of workouts by hand.
          </p>
          <p>
            Anything already sent to your watch is taken off it as part of the
            same operation, so you are not left with weeks of ghost sessions
            scheduled on your wrist.
          </p>
        </InfoButton>
      </div>

      <ul className="reset-list">
        {TARGETS.map((t) => (
          <li key={t.key} className="reset-row">
            <label>
              <input
                type="checkbox"
                checked={picked.has(t.key)}
                onChange={() => toggle(t.key)}
              />
              <span>
                <span className="reset-title">{t.title}</span>
                <span className="reset-sub">{t.sub}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>

      {!nothing && (
        <div className="reset-confirm">
          <label className="field-label reset-type" htmlFor="reset-confirm">
            Type <b>CLEAR</b> to confirm
          </label>
          <input
            id="reset-confirm"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="CLEAR"
          />
          <button
            type="button"
            className="btn btn-danger btn-grow"
            disabled={!ready || reset.isPending}
            onClick={() => {
              const body: Record<string, unknown> = { confirm: 'CLEAR' }
              for (const t of TARGETS) body[t.key] = picked.has(t.key)
              reset.mutate(body)
            }}
          >
            {reset.isPending ? 'Clearing…' : `Clear ${picked.size} thing${picked.size === 1 ? '' : 's'}`}
          </button>
        </div>
      )}

      {reset.error && (
        <p className="small bad" role="alert">
          {errorText(reset.error, 'Nothing was cleared.')}
        </p>
      )}

      {done && (
        <div className="reset-done" role="status">
          <p className="reset-title">Cleared</p>
          <ul>
            {Object.entries(done)
              .filter(([, n]) => n > 0)
              .map(([key, n]) => (
                <li key={key}>
                  <b className="num">{n}</b> {LABEL[key] ?? key}
                </li>
              ))}
          </ul>
          {Object.values(done).every((n) => !n) && (
            <p className="small muted">There was nothing there to clear.</p>
          )}
          <p className="small muted">
            Fetch your history below, then ask the coach for a new plan.
          </p>
        </div>
      )}
    </section>
  )
}
