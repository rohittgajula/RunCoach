/**
 * What to eat today.
 *
 * Built from his own constraints rather than a generic meal plan: what his PG
 * serves, what he can cook on an induction plate, what he has said he eats most
 * days, what his last blood panel flagged, and what today's training asks for.
 *
 * Every number on this screen was summed in Python from a food table. The model
 * chose which foods and how many portions and wrote the one-liners; it never saw
 * a calorie. That is why portions can be shown next to macros without hedging —
 * "2 katori sambar" means a fixed number of grams of protein here, not an
 * estimate of one.
 *
 * Two tags carry most of the meaning, so they are visual rather than written out:
 *
 *   PG      already paid for and waiting downstairs. The plan builds around these
 *           instead of asking him to cook what is already cooked.
 *   yours   the oats and eggs he told the app he eats anyway, kept rather than
 *           re-suggested as though they were the app's idea.
 */

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { ChevronDown, RefreshIcon } from '../Icons'
import { Skeleton } from '../States'

type Item = {
  key: string; text: string; name: string; portions: number
  from_pg: boolean; staple: boolean; haem_iron: boolean; note: string
  kcal: number; protein_g: number; carbs_g: number; fat_g: number; iron_mg: number
}
type Meal = {
  slot: 'breakfast' | 'lunch' | 'snack' | 'dinner'
  items: Item[]; why: string
  kcal: number; protein_g: number; carbs_g: number; fat_g: number; iron_mg: number
}
type Plan = {
  meals: Meal[]
  totals: { kcal: number; protein_g: number; carbs_g: number; fat_g: number; iron_mg: number; haem_iron_mg: number; vitamin_c_mg: number }
  left_before: { kcal: number; protein_g: number; carbs_g: number; fat_g: number }
  budgets: Record<string, { kcal: number; protein_g: number }>
  over_by_pct: number
  iron: { total_mg: number; haem_mg: number; vitamin_c_mg: number; target_mg: number; paired: boolean }
  headline: string
  focus: string[]
  bloods: { taken_on: string | null; flagged: { key: string; label: string }[] }
  standing_note: string
}

const SLOT_LABEL: Record<Meal['slot'], string> = {
  breakfast: 'Breakfast', lunch: 'Lunch', snack: 'Snack', dinner: 'Dinner',
}

/**
 * Building a day takes thirty to forty seconds — a long prompt, a careful model,
 * and sometimes a second pass when the first plan comes out over budget. A
 * spinner for that long reads as broken, so say what is actually happening. The
 * last line stays up rather than cycling back, because a loader that loops
 * forever is how you tell someone to give up.
 */
const STEPS: { at: number; say: string }[] = [
  { at: 0, say: 'Reading your targets and today’s session…' },
  { at: 4, say: 'Looking at what your PG serves and what you can cook…' },
  { at: 9, say: 'Checking what your last blood panel flagged…' },
  { at: 15, say: 'Putting the meals together…' },
  { at: 26, say: 'Checking it fits inside your day…' },
  { at: 38, say: 'Nearly there — this one is taking a while.' },
]

function useProgress(active: boolean) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    if (!active) { setSeconds(0); return }
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => window.clearInterval(id)
  }, [active])
  let say = STEPS[0].say
  for (const step of STEPS) if (seconds >= step.at) say = step.say
  return say
}

export function DayPlan() {
  const [open, setOpen] = useState(false)
  const plan = useQuery({
    queryKey: ['diet-plan'],
    queryFn: () => api<Plan>('/diet/plan/'),
    // A model call per view would be wasteful and slow; the day does not change
    // minute to minute, and "Build it again" is right there when it should.
    staleTime: 30 * 60_000,
    enabled: open,
    retry: false,
  })

  if (!open) {
    return (
      <section className="card dp-invite">
        <div>
          <h2 className="card-title">What to eat today</h2>
          <p className="muted small">
            A day built from your PG menu, what you can cook, and anything your
            bloods flagged.
          </p>
        </div>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setOpen(true)}>
          Plan my day
        </button>
      </section>
    )
  }

  return (
    <section className="card stack dp">
      <div className="dp-head">
        <h2 className="card-title">What to eat today</h2>
        <button
          type="button" className="icon-btn" aria-label="Build it again"
          disabled={plan.isFetching} onClick={() => plan.refetch()}
        >
          <RefreshIcon className={plan.isFetching ? 'spin' : ''} />
        </button>
      </div>

      {plan.isPending && <Building />}

      {plan.isError && (
        <p className="small bad" role="alert">
          {errorText(plan.error, 'Could not build a day right now.')}
        </p>
      )}

      {plan.data && <PlanBody plan={plan.data} />}
    </section>
  )
}

function Building() {
  const say = useProgress(true)
  return (
    <>
      <p className="dp-building" role="status">{say}</p>
      <Skeleton lines={6} />
    </>
  )
}

function PlanBody({ plan }: { plan: Plan }) {
  const { totals, left_before: left } = plan
  return (
    <>
      <p className="dp-headline">{plan.headline}</p>

      <ul className="dp-totals">
        <Total value={totals.kcal} of={left.kcal} label="kcal" />
        <Total value={totals.protein_g} of={left.protein_g} label="g protein" />
        <Total value={totals.carbs_g} of={left.carbs_g} label="g carbs" />
        <Total value={totals.iron_mg} of={plan.iron.target_mg} label="mg iron" decimal />
      </ul>

      {plan.meals.map((meal) => <MealBlock key={meal.slot} meal={meal} />)}

      {plan.iron.haem_mg > 0 || plan.iron.paired ? (
        <p className="dp-iron">
          {plan.iron.haem_mg > 0 && (
            <>{plan.iron.haem_mg} mg of today’s iron is the kind your body absorbs easily. </>
          )}
          {plan.iron.paired && <>There’s enough vitamin C alongside it to help the rest.</>}
        </p>
      ) : null}

      {!!plan.focus.length && (
        <ul className="dp-focus">
          {plan.focus.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}

      {!!plan.bloods.flagged.length && (
        <p className="muted small">
          Shaped by {plan.bloods.flagged.map((f) => f.label).join(', ')} from your
          panel on {plan.bloods.taken_on}.
        </p>
      )}
      <p className="muted small">{plan.standing_note}</p>
    </>
  )
}

function Total({ value, of, label, decimal }: { value: number; of: number; label: string; decimal?: boolean }) {
  const pct = of > 0 ? Math.round((value / of) * 100) : null
  const show = decimal ? value.toFixed(1) : Math.round(value)
  return (
    <li>
      <span className="dp-total num">{show}</span>
      <span className="dp-total-of">of {decimal ? of.toFixed(0) : Math.round(of)}</span>
      <span className="dp-total-lbl">{label}</span>
      {pct != null && <span className={`dp-pct${pct > 110 ? ' is-over' : pct >= 90 ? ' is-on' : ''}`}>{pct}%</span>}
    </li>
  )
}

function MealBlock({ meal }: { meal: Meal }) {
  const [why, setWhy] = useState(false)
  return (
    <div className="dp-meal">
      <div className="dp-meal-head">
        <span className="dp-slot">{SLOT_LABEL[meal.slot]}</span>
        <span className="dp-meal-nums num">{meal.kcal} kcal · {meal.protein_g}g P</span>
      </div>
      <ul className="dp-items">
        {meal.items.map((item) => (
          <li key={item.key}>
            <span className="dp-item-text">{item.text}</span>
            {item.from_pg && <span className="dp-tag is-pg">PG</span>}
            {item.staple && <span className="dp-tag is-staple">yours</span>}
            {item.haem_iron && <span className="dp-tag is-iron">iron</span>}
          </li>
        ))}
      </ul>
      {meal.why && (
        <button type="button" className="dp-why" aria-expanded={why} onClick={() => setWhy((w) => !w)}>
          <ChevronDown size={14} className={why ? 'is-open' : ''} /> {why ? meal.why : 'Why this'}
        </button>
      )}
    </div>
  )
}
