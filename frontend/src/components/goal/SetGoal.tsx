/**
 * A distance by a date — and the choice of what that sentence means.
 *
 * The planner has had this mode for a while and exactly one door into it: say
 * the right thing to the coach and hope it picks the right tool. Rohit asked
 * for "5k between march and april with breaks", and the mode had no way to
 * express "with breaks" at all — so the best outcome available was a confident
 * refusal of a goal he had not set.
 *
 * Two decisions shape this screen.
 *
 * **The choice comes first, and both options stay on screen.** Covering 5 km
 * with walking breaks and running 5 km without stopping are different goals
 * whose honest dates can be a year apart. A control that defaults to one of
 * them and hides the other is how somebody trains for months toward a thing
 * they did not pick. Both are answered, together, every time.
 *
 * **The answer arrives before the plan does.** This is the only planner here
 * that will tell you a date does not work, and a refusal you discover after a
 * plan has been written, named and proposed is delivered too late to act on.
 * The preview writes nothing; the button to build it appears underneath the
 * answer, not above it.
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../../lib/auth'
import { errorText, invalidatePlanData } from '../../lib/queries'
import type { PlanSummary } from '../../lib/types'
import { PlanProposalCard } from '../PlanProposalCard'
import { InfoButton } from '../health/InfoButton'

type Style = 'run_walk' | 'nonstop'

type Verdict = {
  style: Style
  label: string
  achievable: boolean
  weeks_needed: number | null
  earliest_date: string | null
  session_s?: number
  blended_pace_s_per_km?: number
  needs_continuous_s?: number
  reaches_continuous_s?: number
  needs_covered_m?: number
  reaches_covered_m?: number
}

type Preview = { asked: Style; plan_start: string; styles: Record<Style, Verdict> }

/** The two readings, in the words somebody would use for them rather than the
 *  words the code uses. `run_walk` leads because it is what most people mean. */
const STYLES: { key: Style; title: string; sub: string }[] = [
  {
    key: 'run_walk',
    title: 'Cover it, with walk breaks',
    sub: 'Run, walk, run. Finishing is the goal and stopping to walk is part of the plan, not a failure in it.',
  },
  {
    key: 'nonstop',
    title: 'Run it without stopping',
    sub: 'The whole distance as one unbroken run. A much harder thing, and usually a much later date.',
  },
]

const DISTANCES = [3, 5, 10, 21.1]

function mmss(seconds: number): string {
  const s = Math.round(seconds)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function longDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    day: 'numeric', month: 'long', year: 'numeric',
  })
}

/** One style's answer. Deliberately says the same things in the same order for
 *  both, so the pair can be read as a comparison rather than two paragraphs. */
function VerdictCard({ v, chosen, onChoose, breaksHaveADate }: {
  v: Verdict; chosen: boolean; onChoose: () => void
  /** Whether the OTHER card found a date. The non-stop card points at walk
   *  breaks when it has no date of its own, and it must not promise one that
   *  the card beside it did not actually find. */
  breaksHaveADate: boolean
}) {
  const meta = STYLES.find((s) => s.key === v.style)!
  return (
    <button
      type="button"
      className={`goal-verdict${chosen ? ' is-chosen' : ''}${v.achievable ? ' is-yes' : ' is-no'}`}
      aria-pressed={chosen}
      onClick={onChoose}
    >
      <span className="goal-verdict-head">
        <span className="goal-verdict-title">{meta.title}</span>
        <span className={`goal-chip ${v.achievable ? 'ok' : 'no'}`}>
          {v.achievable ? 'Realistic' : 'Not by then'}
        </span>
      </span>

      <span className="goal-verdict-date">
        {v.earliest_date
          ? <>Earliest <b>{longDate(v.earliest_date)}</b></>
          : <>No honest date from where you are</>}
      </span>

      {v.style === 'run_walk' && v.session_s ? (
        <span className="muted small">
          About {Math.round(v.session_s / 60)} min on your feet
          {v.blended_pace_s_per_km ? <> at {mmss(v.blended_pace_s_per_km)}/km with the breaks</> : null}
          {/* The counterpart of the non-stop card's "you reach 21 min by then".
              Both cards say the same things in the same order, or the pair stops
              being a comparison and becomes two paragraphs. */}
          {v.reaches_covered_m != null
            ? <> · you cover {(v.reaches_covered_m / 1000).toFixed(1)} km by then</>
            : null}
        </span>
      ) : null}

      {v.style === 'nonstop' && v.needs_continuous_s ? (
        <span className="muted small">
          Needs {Math.round(v.needs_continuous_s / 60)} min of unbroken running
          {v.reaches_continuous_s
            ? <> · you reach {Math.round(v.reaches_continuous_s / 60)} min by then</>
            : null}
        </span>
      ) : null}

      {/* The one case worth spelling out: the ceiling on continuous running
          means some distances have no non-stop date at all, and the answer the
          athlete wants is usually sitting in the card next to it. Usually, not
          always — so the pointer is only given when that card really found a
          date. */}
      {v.style === 'nonstop' && !v.earliest_date ? (
        <span className="muted small">
          The long run stops progressing at 75 minutes, so there is no date to give
          you.{breaksHaveADate ? ' With walk breaks there is one.' : ''}
        </span>
      ) : null}
    </button>
  )
}

export function SetGoal() {
  const client = useQueryClient()
  const [distance, setDistance] = useState('5')
  const [date, setDate] = useState('')
  const [style, setStyle] = useState<Style>('run_walk')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [proposal, setProposal] = useState<PlanSummary | null>(null)

  const body = () => ({
    target_distance_km: Number(distance),
    target_date: date,
    style,
  })

  const ask = useMutation({
    mutationFn: () => api<Preview>('/plans/goal/preview/', { method: 'POST', ...json(body()) }),
    onSuccess: setPreview,
  })

  const build = useMutation({
    mutationFn: () => api<PlanSummary>('/plans/goal/', { method: 'POST', ...json(body()) }),
    onSuccess: (plan) => {
      invalidatePlanData(client)
      // Shown here rather than navigated to. The same proposal card the coach
      // uses, so accepting a goal is the one gesture it already is everywhere
      // else — and so the answer that justified the plan is still on screen
      // above it while they decide.
      setProposal(plan)
    },
  })

  const ready = Number(distance) > 0 && date !== ''
  // Any edit invalidates the answer on screen. An answer to a question you
  // have since changed is worse than no answer: it is a wrong one that looks
  // considered.
  const change = <T,>(set: (v: T) => void) => (value: T) => {
    setPreview(null)
    setProposal(null)
    set(value)
  }

  return (
    <>
      <section className="card stack">
        <div className="row">
          <strong>What are you aiming at?</strong>
          <InfoButton title="Two different goals">
            <p>
              "A 5k" means one of two things, and they are months or years
              apart. Covering 5 km with walking breaks is a question about time
              on your feet. Running 5 km without stopping is a question about
              your longest unbroken block, which grows far more slowly and
              stops growing at 75 minutes.
            </p>
            <p>
              Both are answered here, every time, so the one you pick is a
              choice rather than a default.
            </p>
          </InfoButton>
        </div>

        <div className="goal-field">
          {/* The unit belongs on the label, not implied by the pills. The box
              below them showed a bare "5" next to a pill reading "5 km", which
              reads like two different numbers. */}
          <span className="field-label">Distance (km)</span>
          <div className="goal-pills">
            {DISTANCES.map((km) => (
              <button
                key={km}
                type="button"
                className={`goal-pill${Number(distance) === km ? ' is-on' : ''}`}
                onClick={() => change(setDistance)(String(km))}
              >
                {km} km
              </button>
            ))}
          </div>
          <input
            type="number" min={0.4} max={100} step={0.1} inputMode="decimal"
            value={distance}
            onChange={(e) => change(setDistance)(e.target.value)}
            aria-label="Distance in kilometres"
          />
        </div>

        <div className="goal-field">
          <label className="field-label" htmlFor="goal-date">By when</label>
          <input
            id="goal-date" type="date" value={date}
            onChange={(e) => change(setDate)(e.target.value)}
          />
        </div>

        <fieldset className="goal-styles">
          <legend className="field-label">Which do you mean?</legend>
          {STYLES.map((s) => (
            <label key={s.key} className={`goal-style${style === s.key ? ' is-on' : ''}`}>
              <input
                type="radio" name="goal-style" value={s.key}
                checked={style === s.key}
                onChange={() => change(setStyle)(s.key)}
              />
              <span>
                <span className="reset-title">{s.title}</span>
                <span className="reset-sub">{s.sub}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <button
          type="button"
          className="btn btn-secondary btn-grow"
          disabled={!ready || ask.isPending}
          onClick={() => ask.mutate()}
        >
          {ask.isPending ? 'Working it out…' : 'Is that realistic?'}
        </button>
        {ask.error && (
          <p className="small bad" role="alert">
            {errorText(ask.error, 'Could not work that out.')}
          </p>
        )}
      </section>

      {preview && (
        <section className="card stack" aria-live="polite">
          <div className="row">
            <strong>Both answers</strong>
          </div>
          <p className="muted small reset-sub">
            Measured against your own runs, at your own pace, with the same weekly
            limit a plan is built under. Tap whichever one you want to train for.
          </p>

          <div className="goal-verdicts">
            {STYLES.map((s) => (
              <VerdictCard
                key={s.key}
                v={preview.styles[s.key]}
                chosen={style === s.key}
                onChoose={() => setStyle(s.key)}
                breaksHaveADate={preview.styles.run_walk.earliest_date != null}
              />
            ))}
          </div>

          {!proposal && (
            <>
              <button
                type="button"
                className="btn btn-primary btn-grow"
                disabled={build.isPending}
                onClick={() => build.mutate()}
              >
                {build.isPending
                  ? 'Building…'
                  : `Build the plan for "${preview.styles[style].label}"`}
              </button>
              {/* Said plainly rather than hidden behind the word "proposal". */}
              <p className="small muted">
                Nothing reaches your calendar until you accept it.
              </p>
            </>
          )}
          {build.error && (
            <p className="small bad" role="alert">
              {errorText(build.error, 'The plan could not be built.')}
            </p>
          )}
        </section>
      )}

      {proposal && <PlanProposalCard plan={proposal} />}
    </>
  )
}
