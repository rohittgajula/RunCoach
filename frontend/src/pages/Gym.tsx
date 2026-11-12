/**
 * Gym — the strength work, and the running form it exists to protect.
 *
 * Its own tab rather than a card inside Plan, because it is the half of the
 * training Rohit is newest at and the half that needs looking at *while doing
 * it*. A gym session is read standing up between sets, one exercise at a time,
 * which is a different act from glancing at tomorrow's run.
 *
 * The figure comes before the numbers on each movement. "Sit back until you
 * touch the chair" is a sentence somebody reads once, believes they have
 * understood, and then performs as a knees-forward squat; the drawing is the
 * only part of this screen that can prevent that.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/auth'
import { dur } from '../lib/format'
import { PageHeader } from '../components/PageHeader'
import { ErrorState, Loading } from '../components/States'
import { ExerciseFigure } from '../components/gym/ExerciseFigure'
import { FormFigure } from '../components/gym/FormFigure'

type Exercise = {
  key: string
  pattern: string
  name: string
  sets: number
  reps: number | null
  seconds: number | null
  per_side: boolean
  rest_s: number
  load: string
  cue: string
  why: string
  level: number
  max_level: number
  ceiling: number
  at_ceiling: boolean
  graduate_when: string
  is_warmup?: boolean
}

type Session = {
  id: number
  date: string
  title: string
  duration_s: number
  level: number
  status: string
  after_run: boolean
  exercises: Exercise[]
}

type Ladder = {
  key: string
  pattern: string
  why: string
  max_level: number
  steps: { name: string; load: string; graduate_when: string }[]
}

type Payload = {
  per_week: number
  suggested: number
  equipment: string
  equipment_options: string[]
  gym_days: Record<string, boolean>
  levels: Record<string, number>
  ladders: Ladder[]
  sessions: Session[]
}

const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const EQUIPMENT_LABEL: Record<string, string> = {
  bodyweight: 'Bodyweight only',
  dumbbells: 'Dumbbells',
  gym: 'Full gym',
}

function doseOf(e: Exercise): string {
  const amount = e.reps != null ? `${e.reps}` : `${e.seconds}s`
  return `${e.sets} × ${amount}${e.per_side ? ' a side' : ''}`
}

function Rungs({ level, max, ceiling }: { level: number; max: number; ceiling: number }) {
  return (
    <div className="rungs" aria-label={`Level ${level} of ${max}`}>
      {Array.from({ length: max }).map((_, i) => {
        const rung = i + 1
        // Beyond what the available equipment can reach is drawn differently
        // from "not there yet" — one is progress still to make, the other is a
        // dumbbell away, and conflating them hides which.
        const state = rung <= level ? 'on' : rung <= ceiling ? '' : 'locked'
        return <i key={rung} className={state} />
      })}
    </div>
  )
}

function ExerciseCard({ exercise }: { exercise: Exercise }) {
  return (
    <li className="gym-ex">
      <div className="gym-ex-head">
        <span className="gym-ex-pattern">{exercise.pattern}</span>
        <span className="gym-ex-dose num">{doseOf(exercise)}</span>
      </div>
      <h3 className="gym-ex-name">{exercise.name}</h3>

      <ExerciseFigure pattern={exercise.key} name={exercise.name} />

      <p className="gym-ex-cue">{exercise.cue}</p>
      <p className="small muted gym-ex-load">{exercise.load} · {exercise.rest_s}s rest</p>

      <Rungs level={exercise.level} max={exercise.max_level} ceiling={exercise.ceiling} />
      <p className="small muted gym-ex-next">
        {exercise.at_ceiling
          ? `Top of what you can do with what you have. ${exercise.load.toLowerCase().includes('bodyweight') ? 'A dumbbell opens the next rung.' : 'Change your equipment in Settings to go further.'}`
          : `Move up when: ${exercise.graduate_when}`}
      </p>
    </li>
  )
}


const PATTERN_LABEL: Record<string, string> = {
  calf: 'Calf', squat: 'Squat', hinge: 'Hinge', push: 'Push', pull: 'Pull', core: 'Core',
}

const HOW: { value: number; label: string }[] = [
  { value: 1, label: 'Too easy' },
  { value: 2, label: 'Easy' },
  { value: 3, label: 'About right' },
  { value: 4, label: 'Hard' },
  { value: 5, label: "Couldn't finish" },
]

/**
 * How it went, and what that changes.
 *
 * Two questions, because they are different ones. The overall rating is for the
 * ends of the scale only — "about right" is the common answer and has to be
 * cheap to give. The per-movement ticks are what actually move a ladder, since
 * "that was easy" about six exercises says nothing about which of them it was
 * easy for.
 *
 * The response names what moved, so the athlete sees the programme respond
 * rather than being told it was noted.
 */
function SessionReview({ sessionId, patterns }: { sessionId: number; patterns: string[] }) {
  const client = useQueryClient()
  const [how, setHow] = useState<number | null>(null)
  const [easy, setEasy] = useState<string[]>([])
  const [hard, setHard] = useState<string[]>([])

  const send = useMutation({
    mutationFn: () => api<{ moved: { pattern: string; direction: string; to: string }[]; detail: string }>(
      `/strength/${sessionId}/review/`,
      { method: 'POST', body: JSON.stringify({ difficulty: how, easy, hard }) },
    ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['strength'] }),
  })

  const pick = (pattern: string, list: 'easy' | 'hard') => {
    const [get, set, other, setOther] = list === 'easy'
      ? [easy, setEasy, hard, setHard] as const
      : [hard, setHard, easy, setEasy] as const
    set(get.includes(pattern) ? get.filter((p) => p !== pattern) : [...get, pattern])
    // A movement cannot be both, and the server refuses it — so the UI should
    // not let you build a request it will reject.
    if (other.includes(pattern)) setOther(other.filter((p) => p !== pattern))
  }

  if (send.data) {
    return (
      <div className="gym-review is-done">
        <strong>{send.data.detail}</strong>
        {send.data.moved.length > 0 && (
          <ul>
            {send.data.moved.map((m) => (
              <li key={m.pattern}>
                {PATTERN_LABEL[m.pattern] ?? m.pattern}{' '}
                {m.direction === 'up' ? 'moves up to' : 'steps back to'}{' '}
                <strong>{m.to}</strong>
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  return (
    <div className="gym-review">
      <h3 className="gym-group-title">How did it go?</h3>
      <div className="gym-how">
        {HOW.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`chip-btn ${how === option.value ? 'on' : ''}`}
            onClick={() => setHow(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {how != null && how !== 3 && (
        <div className="gym-per-pattern">
          <p className="small muted">
            Which movements? Leave blank to change all of them.
          </p>
          <div className="gym-pattern-row">
            {patterns.map((pattern) => {
              const list = how <= 2 ? 'easy' : 'hard'
              const on = (list === 'easy' ? easy : hard).includes(pattern)
              return (
                <button
                  key={pattern}
                  type="button"
                  className={`chip-btn ${on ? 'on' : ''}`}
                  onClick={() => pick(pattern, list)}
                >
                  {PATTERN_LABEL[pattern] ?? pattern}
                </button>
              )
            })}
          </div>
        </div>
      )}

      <button
        type="button"
        className="btn btn-primary gym-review-save"
        disabled={how == null || send.isPending}
        onClick={() => send.mutate()}
      >
        {send.isPending ? 'Saving…' : 'Save and adjust'}
      </button>
      {send.isError && <p className="small bad">That did not save. Try again.</p>}
    </div>
  )
}

export default function Gym() {
  const query = useQuery<Payload>({
    queryKey: ['strength', 'gym'],
    queryFn: () => api('/strength/'),
  })

  if (query.isPending) return <Loading />
  if (query.isError || !query.data) {
    return <ErrorState message="The gym plan did not load." onRetry={() => query.refetch()} />
  }

  const { sessions, equipment, per_week, gym_days, ladders } = query.data
  const today = new Date().toISOString().slice(0, 10)
  const next = sessions.find((s) => s.date >= today && s.status === 'planned') ?? sessions[0]
  const days = DOW.filter((_, i) => gym_days[String(i)])
  // The warm-up arrives in the same list as the lifts, flagged, so the screen
  // can group them without the API having to send two shapes.
  const warmup = (next?.exercises ?? []).filter((e) => e.is_warmup)
  const main = (next?.exercises ?? []).filter((e) => !e.is_warmup)

  return (
    <div className="page">
      <PageHeader title="Gym" />

      {per_week === 0 ? (
        <section className="card">
          <h2>Not switched on yet</h2>
          <p className="small muted">
            Two sessions a week is the honest start alongside a running build.
            Turn it on in Settings and pick your days.
          </p>
        </section>
      ) : (
        <>
          <section className="card gym-summary">
            <div className="row">
              <div>
                <div className="stat-value num">{per_week}<span className="unit">/week</span></div>
                <p className="small muted">{days.length ? days.join(' · ') : 'Days chosen for you'}</p>
              </div>
              <div className="gym-equip">
                <span className="small muted">Equipment</span>
                <strong>{EQUIPMENT_LABEL[equipment] ?? equipment}</strong>
              </div>
            </div>
          </section>

          {next ? (
            <section className="card">
              <div className="row">
                <h2>{next.title}</h2>
                <span className="small muted num">{dur(next.duration_s)}</span>
              </div>
              <p className="small muted">
                {new Date(`${next.date}T00:00:00`).toLocaleDateString(undefined, {
                  weekday: 'long', day: 'numeric', month: 'long',
                })}
                {next.after_run && ' · after your run'}
              </p>
              <p className="small gym-note">
                Finish every set two or three reps short of hard. Walking normally
                tomorrow matters more than how this session went.
              </p>

              {warmup.length > 0 && (
                <div className="gym-group">
                  <h3 className="gym-group-title">
                    Warm up <span className="muted">· 5 min</span>
                  </h3>
                  <p className="small muted gym-group-why">
                    Warm tissue tolerates load; cold tissue tears. This is the part
                    people skip, so it goes first.
                  </p>
                  <ul className="gym-list is-warmup">
                    {warmup.map((e) => <ExerciseCard key={e.key} exercise={e} />)}
                  </ul>
                </div>
              )}

              <div className="gym-group">
                <h3 className="gym-group-title">
                  The session <span className="muted">· {main[0]?.sets ?? 2} sets</span>
                </h3>
                <ul className="gym-list">
                  {main.map((e) => <ExerciseCard key={e.key} exercise={e} />)}
                </ul>
              </div>

              <SessionReview sessionId={next.id} patterns={main.map((e) => e.key)} />
            </section>
          ) : (
            <section className="card">
              <h2>No session scheduled</h2>
              <p className="small muted">
                Nothing in the next few weeks. That usually means a race is close,
                or the days you picked all fall before a long run.
              </p>
            </section>
          )}
        </>
      )}

      <FormFigure cadence={null} />

      <section className="card">
        <h2>Why these six</h2>
        <ul className="gym-why">
          {ladders.map((l) => (
            <li key={l.key}>
              <strong>{l.pattern}</strong>
              <p className="small muted">{l.why}</p>
            </li>
          ))}
        </ul>
        <p className="small muted gym-fat">
          On fat loss: nothing here burns it in a way worth planning around —
          energy balance does that. What lifting does is hold onto muscle while
          the deficit runs, so what you lose is fat rather than the legs you need.
        </p>
      </section>
    </div>
  )
}
