import { useState } from 'react'
import { todayISO } from '../../lib/format'
import { useDietDay, useWeatherToday } from '../../lib/queries'

type DayType = 'rest' | 'easy' | 'hard'
const PLATES: Record<DayType, { label: string; carbs: number; protein: number; veg: number; note: string }> = {
  rest: { label: 'Rest', carbs: 25, protein: 30, veg: 45, note: 'Half the plate vegetables and fruit, a palm of protein, a small portion of whole grains.' },
  easy: { label: 'Easy', carbs: 35, protein: 25, veg: 40, note: 'A bit more rice, roti or potatoes than on a rest day.' },
  hard: { label: 'Hard / long', carbs: 50, protein: 25, veg: 25, note: 'Half the plate carbs to refill the tank; still a palm of protein.' },
}

/** A pie "plate": carbs · protein · veg arcs. */
function Plate({ type }: { type: DayType }) {
  const p = PLATES[type]
  const parts = [
    { key: 'veg', pct: p.veg, cls: 'is-veg', label: 'Veg & fruit' },
    { key: 'carbs', pct: p.carbs, cls: 'is-carbs', label: 'Carbs' },
    { key: 'protein', pct: p.protein, cls: 'is-protein', label: 'Protein' },
  ]
  const r = 40
  const c = 2 * Math.PI * r
  let offset = 0
  return (
    <div className="plate">
      <svg viewBox="0 0 120 120" className="plate-svg" role="img" aria-label={`Plate: ${parts.map((x) => `${x.label} ${x.pct}%`).join(', ')}`}>
        <circle cx={60} cy={60} r={56} className="plate-rim" />
        <circle cx={60} cy={60} r={50} className="plate-base" />
        <g transform="rotate(-90 60 60)">
          {parts.map((x) => {
            const len = (x.pct / 100) * c
            const el = (
              <circle
                key={x.key}
                cx={60} cy={60} r={r}
                className={`plate-part ${x.cls}`}
                strokeDasharray={`${len - 1.5} ${c - len + 1.5}`}
                strokeDashoffset={-offset}
              />
            )
            offset += len
            return el
          })}
        </g>
      </svg>
      <ul className="plate-legend">
        {parts.map((x) => (
          <li key={x.key}><i className={`plate-key ${x.cls}`} />{x.label} <b>{x.pct}%</b></li>
        ))}
      </ul>
    </div>
  )
}

const ml = (v: number | string | null | undefined) => (v == null || v === '' ? null : typeof v === 'number' ? `${Math.round(v)} ml` : v)

export function FuelingGuide() {
  const [type, setType] = useState<DayType>('easy')
  const day = useDietDay(todayISO())
  const weather = useWeatherToday()
  const targets = day.data?.targets
  const fuel = day.data?.fueling?.[0]
  const hydration = weather.data?.hydration ?? null
  const carbs = targets?.carbs_g
  const protein = targets?.protein_g
  const duringCarbs = fuel?.carbs_g_during_per_h
  const during = hydration?.during_ml_per_h
  const duringWater = during && during !== '0' ? `${ml(during)} water per hour` : 'water in sips to thirst'
  const hot = (weather.data?.daily_water_bonus_ml ?? 0) > 0 || weather.data?.heat === 'hot' || weather.data?.heat === 'very_hot'

  const steps = [
    {
      when: '3 h before',
      title: 'Normal meal',
      text: carbs
        ? `Carb-based and familiar — about ${Math.round(carbs * 0.3)} g of today’s ${Math.round(carbs)} g carbs. Go easy on fat, fibre and spice.`
        : 'Carb-based and familiar — rice, oats, bread, potatoes. Go easy on fat, fibre and spice.',
      extra: fuel?.before,
    },
    {
      when: '60 min',
      title: 'Top up',
      text: `Small snack of 20–30 g carbs (a banana, toast with honey) and ${ml(hydration?.before_ml) ?? '300–500 ml'} water.`,
    },
    {
      when: 'During',
      title: 'Under 60 min: water only',
      text: `Longer: ${duringCarbs ? `${Math.round(duringCarbs)} g` : '30–60 g'} carbs per hour from 45 min, and ${duringWater}.${hydration?.electrolytes ? ' Add electrolytes today.' : ''}`,
      extra: fuel?.during,
    },
    {
      when: '≤ 30 min after',
      title: 'Recover',
      text: `20–25 g protein with carbs (curd rice, milk + fruit, eggs on toast)${protein ? `; spread the rest of today’s ${Math.round(protein)} g protein over the day` : ''}.`,
      extra: fuel?.after ?? hydration?.after_note,
    },
  ]

  return (
    <div className="stack">
      <section className="card stack guide-block">
        <h3 className="habit-sub">Around a run</h3>
        <svg viewBox="0 0 320 56" className="fuel-line" role="img" aria-label="Timeline: 3 hours before, 60 minutes before, during, within 30 minutes after">
          <line x1={20} y1={22} x2={300} y2={22} className="fuel-axis" />
          <rect x={196} y={16} width={56} height={12} rx={6} className="fuel-run" />
          {[{ x: 20, t: '3 h' }, { x: 120, t: '60 min' }, { x: 224, t: 'Run' }, { x: 300, t: '+30 min' }].map((p, i) => (
            <g key={p.t}>
              <circle cx={p.x} cy={22} r={7} className={`fuel-dot is-${i}`} />
              <text x={p.x} y={48} textAnchor={i === 0 ? 'start' : i === 3 ? 'end' : 'middle'}>{p.t}</text>
            </g>
          ))}
        </svg>
        <ol className="fuel-steps">
          {steps.map((s, i) => (
            <li key={s.when} className="fuel-step">
              <span className={`fuel-badge is-${i}`}>{s.when}</span>
              <div className="grow">
                <p className="cue-title">{s.title}</p>
                <p className="small">{s.text}</p>
                {s.extra && <p className="muted small">Today: {s.extra}</p>}
              </div>
            </li>
          ))}
        </ol>
        {targets && (
          <p className="muted small">
            Today’s targets: {Math.round(targets.kcal)} kcal · {Math.round(targets.carbs_g)} g carbs · {Math.round(targets.protein_g)} g protein · {(targets.water_ml / 1000).toFixed(1)} L water
          </p>
        )}
        {hot && <p className="hot-tip small">Hot day: drink with every meal, add salt or electrolytes, and run in the cooler hours.</p>}
      </section>
      <section className="card stack guide-block">
        <h3 className="habit-sub">Plate by day type</h3>
        <div className="segmented segmented-full" role="radiogroup" aria-label="Day type">
          {(Object.keys(PLATES) as DayType[]).map((k) => (
            <button key={k} type="button" role="radio" aria-checked={type === k} className={`segmented-option ${type === k ? 'is-active' : ''}`} onClick={() => setType(k)}>
              {PLATES[k].label}
            </button>
          ))}
        </div>
        <Plate type={type} />
        <p className="muted small">{PLATES[type].note}</p>
      </section>
    </div>
  )
}
