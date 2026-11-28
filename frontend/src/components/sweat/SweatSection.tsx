/**
 * Sweat tests: your own litres per hour, instead of a table's.
 *
 * Every hydration figure in the app — the daily water target, the drinking plan
 * for a long run, the fuel plan on race day — comes from three population
 * averages keyed on how hot it is (`analysis/weather_advice.SWEAT_L_H`). Sweat
 * rate varies between people by a factor of three at the same temperature, so for
 * plenty of runners those numbers are wrong by more than half, and no amount of
 * weather data narrows it down. Two weigh-ins either side of one run fixes it
 * permanently.
 *
 * The screen is built around the comparison, because that is the whole argument:
 * what the app guessed, what he actually sweats, and what the difference does to
 * the run in front of him. A measured rate that lands on the table value is a
 * useful outcome too, not a wasted morning.
 *
 * Nothing here computes anything. The rate, the percentages, the drinking plan
 * and every refusal come from `analysis/sweat.py`; this file asks and lays out.
 * That matters most for the refusals — a mis-typed weight produces a plausible
 * rate roughly twice the real one, which would tell him to drink the cap when he
 * needs half of it, so the server rejects it with a reason and the screen shows
 * the reason rather than a number.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { todayISO } from '../../lib/format'
import { DropIcon, RunIcon, SparkIcon } from '../Icons'
import { Field } from '../Field'
import { CardHead } from '../Kit'
import { Empty, ErrorState, Skeleton } from '../States'

type Loss = { sweat_l: number; deficit_l: number; pct_lost: number; flag: string | null }
type Plan = { during_ml_per_h: number; rate_l_h: number; sweat_l?: number
              after_ml?: number; too_short?: boolean }
type Measured = { rate_l_h: number; source: string; from_band: string | null; tests: number }
type Test = {
  id: number; done_on: string; minutes: number
  weight_before_kg: number; weight_after_kg: number; drank_ml: number
  band: string | null; feels_like_c: number | null; note: string
  usable: boolean; problem?: string
  sweat_l?: number; rate_l_h?: number; pct_lost?: number; flag?: string | null
}
type Band = { table_l_h: number; measured: Measured | null; plan: Plan }
type Today = {
  title: string; kind: string; minutes: number; band: string
  feels_like_c: number | null; source: string; from_band: string | null; plan: Plan
  if_you_drink_nothing?: Loss; if_you_follow_the_plan?: Loss
}
type Body = {
  tests: Test[]
  rates: Record<'cool' | 'warm' | 'hot', Band>
  today: Today | null
  how_to: { steps: string[]; best_run: string }
  standing_note: string
}

const BANDS: Array<{ key: 'cool' | 'warm' | 'hot'; label: string; sub: string }> = [
  { key: 'cool', label: 'Cool', sub: 'under 24°C' },
  { key: 'warm', label: 'Warm', sub: '24–32°C' },
  { key: 'hot', label: 'Hot', sub: 'over 32°C' },
]

/** Said in words, because "scaled" on its own invites being read as measured. */
function provenance(m: Measured | null): string {
  if (!m) return 'The app’s guess for this weather — you have not tested in it'
  if (m.source === 'measured') {
    return m.tests === 1 ? 'Your own, from one test' : `Your own, from ${m.tests} tests`
  }
  if (m.source === 'scaled') return `Scaled from your ${m.from_band}-weather test`
  return 'Your own, from tests with no weather recorded'
}

const FLAG_SAID: Record<string, string> = {
  dehydrated: 'past 2% down — that costs you pace',
  severe: 'past 4% down — that is a reason to stop, not to push',
}

export function SweatSection() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const q = useQuery<Body>({ queryKey: ['sweat'], queryFn: () => api<Body>('/health/sweat/') })

  const remove = useMutation({
    mutationFn: (id: number) => api(`/health/sweat/${id}/`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sweat'] }),
  })

  if (q.isLoading) return <Skeleton lines={6} />
  if (q.error) return <ErrorState message={errorText(q.error)} onRetry={() => q.refetch()} />
  const body = q.data
  if (!body) return null

  return (
    <div className="stack">
      {body.today && <TodayRun today={body.today} />}

      <section className="card stack">
        <CardHead
          title={<><DropIcon size={18} /> How much you sweat</>}
          sub="Your rate against the one the app assumes, for each kind of weather"
        />
        <ul className="sweat-bands">
          {BANDS.map(({ key, label, sub }) => {
            const band = body.rates[key]
            const mine = band.measured
            return (
              <li key={key} className={`sweat-band${mine?.source === 'measured' ? ' is-measured' : ''}`}>
                <div className="sweat-band-head">
                  <strong>{label}</strong>
                  <span className="muted small">{sub}</span>
                </div>
                <div className="sweat-band-nums">
                  <span className="num sweat-rate">{(mine?.rate_l_h ?? band.table_l_h).toFixed(2)}</span>
                  <span className="sweat-unit">L/h</span>
                  {mine && mine.rate_l_h !== band.table_l_h && (
                    <span className="muted small sweat-was">app assumed {band.table_l_h.toFixed(2)}</span>
                  )}
                </div>
                <p className="muted small">{provenance(mine)}</p>
                <p className="small">
                  Drink <strong className="num">{band.plan.during_ml_per_h}</strong> ml an hour on a
                  run over 45 minutes.
                </p>
              </li>
            )
          })}
        </ul>
        <p className="lab-standing">{body.standing_note}</p>
      </section>

      <section className="card stack">
        <CardHead title={<><SparkIcon size={18} /> Do a sweat test</>} sub={body.how_to.best_run} />
        <ol className="sweat-steps">
          {body.how_to.steps.map((step) => <li key={step}>{step}</li>)}
        </ol>
        {!open && (
          <button type="button" className="btn btn-primary btn-grow" onClick={() => setOpen(true)}>
            Enter a test
          </button>
        )}
        {open && <TestForm onDone={() => setOpen(false)} />}
      </section>

      <section className="card stack">
        <CardHead title="Your tests" />
        {!body.tests.length && (
          <Empty icon={<DropIcon size={28} />} title="No tests yet">
            One weigh-in either side of a long run is enough to replace the guess.
          </Empty>
        )}
        {!!body.tests.length && (
          <ul className="sweat-list">
            {body.tests.map((t) => (
              <li key={t.id} className="sweat-row">
                <div className="sweat-row-main">
                  <strong>{t.done_on}</strong>
                  <span className="muted small">
                    {t.minutes} min
                    {t.band ? ` · ${t.band}` : ''}
                    {t.feels_like_c != null ? ` · felt like ${Math.round(t.feels_like_c)}°C` : ''}
                  </span>
                </div>
                {t.usable ? (
                  <div className="sweat-row-nums">
                    <span><span className="num">{t.rate_l_h?.toFixed(2)}</span> L/h</span>
                    <span className="muted small">
                      {t.sweat_l?.toFixed(2)} L sweat · {t.pct_lost?.toFixed(1)}% down
                      {t.flag ? ` — ${FLAG_SAID[t.flag] ?? t.flag}` : ''}
                    </span>
                  </div>
                ) : (
                  <p className="small bad">{t.problem}</p>
                )}
                <button
                  type="button" className="btn btn-ghost btn-sm"
                  onClick={() => remove.mutate(t.id)} disabled={remove.isPending}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

/** Today's run, costed in fluid. The reason to have measured at all. */
function TodayRun({ today }: { today: Today }) {
  const dry = today.if_you_drink_nothing
  const wet = today.if_you_follow_the_plan
  return (
    <section className="card stack">
      <CardHead
        title={<><RunIcon size={18} /> {today.title}</>}
        sub={`${today.minutes} min · ${today.band}${
          today.feels_like_c != null ? ` · feels like ${Math.round(today.feels_like_c)}°C` : ''
        }`}
      />
      {today.plan.too_short ? (
        <p className="sweat-lead">
          Too short to need drinking during it
          {today.plan.sweat_l ? <> — about <strong className="num">{today.plan.sweat_l}</strong> L
            of sweat, which you can replace afterwards</> : null}.
        </p>
      ) : (
        <p className="sweat-lead">
          Drink about <strong className="num">{today.plan.during_ml_per_h}</strong> ml an hour
          {today.plan.after_ml ? <> and <strong className="num">{today.plan.after_ml}</strong> ml afterwards</> : null}.
        </p>
      )}
      {/* The two-row comparison only says anything when there is a plan to follow.
          On a run too short to drink on, both rows are the same number. */}
      {!today.plan.too_short && dry && wet && (
        <ul className="sweat-compare">
          <li className={dry.flag ? 'is-bad' : ''}>
            <span className="sweat-lbl">Drinking nothing</span>
            <span className="num">{dry.pct_lost}%</span>
            <span className="muted small">
              down{dry.flag ? ` — ${FLAG_SAID[dry.flag] ?? dry.flag}` : ''}
            </span>
          </li>
          <li className={wet.flag ? 'is-bad' : 'is-good'}>
            <span className="sweat-lbl">Following the plan</span>
            <span className="num">{wet.pct_lost}%</span>
            <span className="muted small">
              down{wet.flag ? ` — ${FLAG_SAID[wet.flag] ?? wet.flag}` : ''}
            </span>
          </li>
        </ul>
      )}
      <p className="muted small">
        {today.source === 'table'
          ? 'From the app’s assumed sweat rate. Do one test and this becomes yours.'
          : provenance({ rate_l_h: today.plan.rate_l_h, source: today.source,
                         from_band: today.from_band, tests: 0 })}
      </p>
    </section>
  )
}

function TestForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    done_on: todayISO(), weight_before_kg: '', weight_after_kg: '',
    drank_ml: '0', minutes: '', feels_like_c: '',
  })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const save = useMutation({
    mutationFn: () => api<Test>('/health/sweat/', {
      method: 'POST',
      ...json({
        done_on: form.done_on,
        weight_before_kg: Number(form.weight_before_kg),
        weight_after_kg: Number(form.weight_after_kg),
        drank_ml: Number(form.drank_ml || 0),
        minutes: Number(form.minutes),
        feels_like_c: form.feels_like_c === '' ? null : Number(form.feels_like_c),
      }),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sweat'] })
      // The whole app's hydration numbers move on this, so the screens that show
      // them must not keep showing the old table answer.
      qc.invalidateQueries({ queryKey: ['weather'] })
      qc.invalidateQueries({ queryKey: ['race-plan'] })
      onDone()
    },
  })

  const ready = form.weight_before_kg && form.weight_after_kg && form.minutes
  return (
    <div className="stack sweat-form">
      {/* Before and after stay side by side: they are read as a pair, and seeing
          them together is what makes a transposed entry obvious. */}
      <div className="sweat-pair">
        <Field label="Weight before (kg)">
          <input type="number" step="0.1" inputMode="decimal"
                 value={form.weight_before_kg} onChange={set('weight_before_kg')} />
        </Field>
        <Field label="Weight after (kg)">
          <input type="number" step="0.1" inputMode="decimal"
                 value={form.weight_after_kg} onChange={set('weight_after_kg')} />
        </Field>
      </div>
      <div className="sweat-pair">
        <Field label="Minutes running">
          <input type="number" inputMode="numeric"
                 value={form.minutes} onChange={set('minutes')} />
        </Field>
        <Field label="Drank during (ml)">
          <input type="number" inputMode="numeric"
                 value={form.drank_ml} onChange={set('drank_ml')} />
        </Field>
      </div>
      <div className="sweat-pair">
        <Field label="Date">
          <input type="date" value={form.done_on} max={todayISO()} onChange={set('done_on')} />
        </Field>
        <Field label="Felt like (°C)" hint="Optional">
          <input type="number" inputMode="decimal"
                 value={form.feels_like_c} onChange={set('feels_like_c')} />
        </Field>
      </div>
      <p className="muted small">
        Leave the temperature blank for today’s run and the weather fills it in. For an
        older run, type what it felt like — otherwise the test is kept but not matched
        to a kind of weather.
      </p>
      {save.error && <p className="small bad" role="alert">{errorText(save.error, 'Could not save that.')}</p>}
      <div className="sweat-actions">
        <button type="button" className="btn btn-primary" disabled={!ready || save.isPending}
                onClick={() => save.mutate()}>
          {save.isPending ? 'Working it out…' : 'Save test'}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onDone}>Cancel</button>
      </div>
    </div>
  )
}
