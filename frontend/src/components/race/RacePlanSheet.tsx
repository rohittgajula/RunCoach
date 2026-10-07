import { useState } from 'react'
import { dur, pace, parseDate } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useRacePlan, type RacePlan, type RaceStrategy } from '../../lib/r13'
import { BottomSheet } from '../BottomSheet'
import { CheckIcon } from '../Icons'
import { CardHead } from '../Kit'
import { InfoButton } from '../health/InfoButton'
import { ErrorState, Skeleton } from '../States'
import { ShareButton } from '../share/ShareButton'

/** Ticks live on this device (a checklist, not data the coach needs). */
const tickKey = (raceId: number) => `rc.race-taper.${raceId}`
function readTicks(raceId: number): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(tickKey(raceId)) || '{}') as Record<string, boolean>
  } catch {
    return {}
  }
}
function writeTicks(raceId: number, ticks: Record<string, boolean>) {
  try {
    localStorage.setItem(tickKey(raceId), JSON.stringify(ticks))
  } catch {
    /* private mode */
  }
}

const clock = (s: number | null | undefined) => {
  if (s == null) return '--'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.round(s % 60)
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}

type Tab = 'pacing' | 'fuel' | 'warmup' | 'taper' | 'morning'
const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'pacing', label: 'Pacing' },
  { key: 'fuel', label: 'Fuel' },
  { key: 'warmup', label: 'Warm-up' },
  { key: 'taper', label: 'Checklist' },
  { key: 'morning', label: 'Race morning' },
]

/** R13 §2: race card → "Race plan": pacing per km, fuel, warm-up, taper checklist, morning. */
export function RacePlanSheet({ raceId, onClose }: { raceId: number | null; onClose: () => void }) {
  const [strategy, setStrategy] = useState<RaceStrategy>('even')
  const plan = useRacePlan(raceId, strategy)
  const p = plan.data
  const [tab, setTab] = useState<Tab>('pacing')
  return (
    <BottomSheet
      open={raceId != null}
      onClose={onClose}
      title="Race plan"
      full
      actions={p ? (
        <ShareButton
          label="Share race plan"
          card={() => ({
            kind: 'race',
            name: p.race.name,
            date: parseDate(p.race.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
            distance_km: p.race.distance_km,
            target_s: p.target?.time_s ?? null,
            pace_s_per_km: p.target?.pace_s_per_km ?? null,
            strategy: p.strategy === 'negative' ? 'negative split' : 'even pace',
          })}
        />
      ) : undefined}
    >
      {plan.isPending && <Skeleton lines={8} />}
      {plan.isError && <ErrorState message={errorText(plan.error, 'The race plan did not load.')} onRetry={() => plan.refetch()} />}
      {!plan.isPending && !plan.isError && !p && (
        <p className="muted">A race plan isn’t available for this race yet.</p>
      )}
      {p && (
        <div className={`stack race-plan ${plan.isPlaceholderData ? 'is-stale' : ''}`}>
          <RaceHead p={p} />
          <div className="race-tabs" role="tablist" aria-label="Race plan sections">
            {TABS.map((t) => (
              <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={`pill-btn ${tab === t.key ? 'is-active' : ''}`} onClick={() => setTab(t.key)}>
                {t.label}
              </button>
            ))}
          </div>
          {tab === 'pacing' && <Pacing p={p} strategy={strategy} onStrategy={setStrategy} />}
          {tab === 'fuel' && <Fuel p={p} />}
          {tab === 'warmup' && <Warmup p={p} />}
          {tab === 'taper' && <Taper p={p} />}
          {tab === 'morning' && <Morning p={p} />}
        </div>
      )}
    </BottomSheet>
  )
}

const SOURCE: Record<string, string> = { goal: 'your goal', prediction: 'your recent runs', garmin: 'Garmin’s race predictor' }

function RaceHead({ p }: { p: RacePlan }) {
  const date = parseDate(p.race.date).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  const t = p.target
  return (
    <section className="card race-head">
      <div className="grow">
        <span className="lbl">{date} · {p.start_time} start · {p.race.distance_km} km</span>
        <p className="kit-title">{p.race.name}</p>
        <p className="muted small">
          {p.days_to_race > 1 ? `${p.days_to_race} days to go` : p.days_to_race === 1 ? 'Tomorrow' : p.days_to_race === 0 ? 'Race day — enjoy it' : 'Race done'}
          {p.start_time_source === 'default' ? ' · start time assumed — add it to the race' : ''}
        </p>
      </div>
      {t && (
        <div className="race-target">
          <span className="lbl">
            Target
            <InfoButton title="Race target">
              <p>The finish time this plan paces you for, from {SOURCE[t.source] ?? t.source}.</p>
              {t.goal_time_s != null && t.predicted_time_s != null && (
                <p>Your goal is {clock(t.goal_time_s)}; your recent runs predict {clock(t.predicted_time_s)}. The plan uses the more realistic one.</p>
              )}
              <p>Starting too fast is the most common race mistake. Holding back in the first kilometre almost always gives a faster finish.</p>
            </InfoButton>
          </span>
          <b>{clock(t.time_s)}</b>
          <span className="muted small">{pace(t.pace_s_per_km)} /km</span>
        </div>
      )}
      {t?.note && <p className="small race-target-note">{t.note}</p>}
    </section>
  )
}

function Pacing({ p, strategy, onStrategy }: { p: RacePlan; strategy: RaceStrategy; onStrategy: (s: RaceStrategy) => void }) {
  return (
    <section className="card stack">
      <CardHead
        title="Pace per km"
        aside={
          <InfoButton title="Even or negative split">
            <p><b>Even pace</b> — the same pace every kilometre. Simple and reliable.</p>
            <p><b>Negative split</b> — start a few seconds per km slower and finish a little faster. Easier on the legs early, and most people race faster this way.</p>
          </InfoButton>
        }
      />
      <div className="segmented segmented-full" role="radiogroup" aria-label="Pacing strategy">
        {(['even', 'negative'] as const).map((s) => (
          <button key={s} type="button" role="radio" aria-checked={strategy === s} className={`segmented-option ${strategy === s ? 'is-active' : ''}`} onClick={() => onStrategy(s)}>
            {s === 'even' ? 'Even pace' : 'Negative split'}
          </button>
        ))}
      </div>
      {!p.available || p.splits.length === 0 ? (
        <p className="muted small">
          {p.reason === 'no_target'
            ? 'No goal time and not enough recent runs to predict one. Add a goal time to the race, or run by feel and keep the first km easy.'
            : 'No pacing for this race yet.'}
        </p>
      ) : (
        <div className="table-wrap">
          <table className="race-splits">
            <thead><tr><th>km</th><th>Pace /km</th><th>Split</th><th>Clock</th></tr></thead>
            <tbody>
              {p.splits.map((s) => (
                <tr key={s.km}>
                  <td>{Number.isInteger(s.km) ? s.km : s.km.toFixed(1)}</td>
                  <td><b>{pace(s.pace_s_per_km)}</b></td>
                  <td>{clock(s.split_s)}</td>
                  <td>{clock(s.elapsed_s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {p.weather && p.weather.pace_slowdown_pct > 0 && (
        <p className="small race-warn">It looks {p.weather.heat.replace('_', ' ')} on race morning — expect about {p.weather.pace_slowdown_pct}% slower. Run by effort, not the watch.</p>
      )}
    </section>
  )
}

const atText = (s: number) => {
  if (s < 0) return `${Math.round(-s / 60)} min before`
  if (s === 0) return 'Start'
  return `${Math.round(s / 60)} min`
}

function Fuel({ p }: { p: RacePlan }) {
  const f = p.fueling
  const w = p.weather
  return (
    <>
      {w && (
        <section className="card stack">
          <CardHead title="Race-morning forecast" sub={`${w.hour} · ${w.date}`} />
          <dl className="kv kv-row kv-row-3">
            <div><dt>Feels like</dt><dd>{w.feels_like_c != null ? `${Math.round(w.feels_like_c)}°` : '--'}</dd></div>
            <div><dt>Humidity</dt><dd>{w.humidity != null ? `${Math.round(w.humidity)}%` : '--'}</dd></div>
            <div><dt>Rain</dt><dd>{w.precip_prob != null ? `${Math.round(w.precip_prob)}%` : '--'}</dd></div>
          </dl>
          {w.advice.length > 0 && <ul className="race-notes small">{w.advice.map((a, i) => <li key={i}>{a}</li>)}</ul>}
        </section>
      )}
      <section className="card stack">
        <CardHead
          title="Fuel & water"
          aside={
            <InfoButton title="Race fuelling">
              <p>Carbs per hour keep your energy up once a race goes past about 75 minutes. Under an hour, water is usually enough.</p>
              <p>Fluid per hour depends on heat and how much you sweat — sip to thirst, don’t force it. Electrolytes help in the heat.</p>
            </InfoButton>
          }
        />
        <dl className="kv kv-row kv-row-3">
          <div><dt>Carbs</dt><dd>{f.carbs_g_per_h ? `${f.carbs_g_per_h} g/h` : '—'}</dd></div>
          <div><dt>Fluid</dt><dd>{f.fluid_ml_per_h ? `${f.fluid_ml_per_h} ml/h` : '—'}</dd></div>
          <div><dt>Salts</dt><dd>{f.electrolytes ? 'Yes' : 'Not needed'}</dd></div>
        </dl>
        {f.items.length > 0 && (
          <ol className="race-timeline">
            {f.items.map((it, i) => (
              <li key={i}>
                <span className="race-when">{atText(it.at_s)}{it.at_km != null ? <small>km {it.at_km}</small> : null}</span>
                <span className="grow"><b>{it.what}</b>{it.amount && <span className="muted small block">{it.amount}</span>}</span>
              </li>
            ))}
          </ol>
        )}
        {f.notes.length > 0 && <ul className="race-notes small muted">{f.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        <p className="muted small">Only use gels and drinks you’ve already tried on a long run.</p>
      </section>
    </>
  )
}

function Warmup({ p }: { p: RacePlan }) {
  return (
    <section className="card stack">
      <CardHead title="Warm-up" sub="Finish it 10–15 minutes before the start." />
      <ol className="race-timeline">
        {p.warmup.map((w, i) => (
          <li key={i}>
            <span className="race-when">{w.duration_s ? dur(w.duration_s) : `${i + 1}`}</span>
            <span className="grow"><b>{w.label}</b>{w.detail && <span className="muted small block">{w.detail}</span>}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

const STATUS_TAG: Record<string, { cls: string; text: string }> = {
  ok: { cls: 'tag-ok', text: 'OK' },
  warn: { cls: 'tag-warn', text: 'Check' },
  todo: { cls: '', text: 'To do' },
  info: { cls: 'tag-plain', text: 'Tip' },
}

function Taper({ p }: { p: RacePlan }) {
  const [ticks, setTicks] = useState(() => readTicks(p.race.id))
  const toggle = (key: string) => {
    const next = { ...ticks, [key]: !ticks[key] }
    setTicks(next)
    writeTicks(p.race.id, next)
  }
  const items = p.taper.items
  const isOn = (t: (typeof items)[number]) => ticks[t.key] ?? t.status === 'ok'
  const done = items.filter(isOn).length
  return (
    <section className="card stack">
      <CardHead
        title="Final 10 days"
        aside={<span className="muted small">{done}/{items.length}</span>}
        sub={p.taper.in_taper ? 'The plan is easing off now. Tick these as you go.' : `Starts ${parseDate(p.taper.starts_on).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} — the plan already eases off then.`}
      />
      <ul className="race-checklist">
        {items.map((t) => {
          const on = isOn(t)
          const tag = STATUS_TAG[t.status]
          return (
            <li key={t.key}>
              <button type="button" role="checkbox" aria-checked={on} className={`race-check ${on ? 'is-on' : ''}`} onClick={() => toggle(t.key)}>
                <span className="race-box" aria-hidden="true">{on && <CheckIcon size={16} />}</span>
                <span className="grow">
                  <b>{t.label}</b>
                  {t.detail && <span className="muted small block">{t.detail}</span>}
                  {t.due_on && <span className="muted small block">By {parseDate(t.due_on).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}</span>}
                </span>
                {tag && t.status !== 'ok' && t.status !== 'todo' && <span className={`tag ${tag.cls}`}>{tag.text}</span>}
              </button>
            </li>
          )
        })}
      </ul>
      <p className="muted small">Ticks are saved on this phone.</p>
    </section>
  )
}

function Morning({ p }: { p: RacePlan }) {
  return (
    <section className="card stack">
      <CardHead title="Race morning" sub={`For a ${p.start_time} start.`} />
      <ol className="race-timeline">
        {p.morning.map((m, i) => (
          <li key={i}>
            <span className="race-when">{m.time}</span>
            <span className="grow"><b>{m.label}</b>{m.detail && <span className="muted small block">{m.detail}</span>}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
