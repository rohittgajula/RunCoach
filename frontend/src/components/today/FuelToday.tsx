import { Link } from 'react-router-dom'
import { todayISO } from '../../lib/format'
import { useDietDay } from '../../lib/queries'
import { ChevronRight } from '../Icons'
import { Meter } from '../Kit'
import { WaterLog } from './WaterLog'

const n = (v: number) => Math.round(v).toLocaleString()

/** Fuel today: kcal and protein against target, the water log (R11) and the hot-day tip. */
export function FuelToday() {
  const today = todayISO()
  const day = useDietDay(today)
  const d = day.data?.date === today ? day.data : undefined
  if (!d) return null
  const t = d.targets
  const tip = d.targets.water_note || d.weather_tips?.[0] || ''
  return (
    <section className="card fuel-today">
      <Link to="/diet" className="fuel-today-link" aria-label="Fuel today — open Diet">
        <div className="kit-head">
          <span className="lbl grow">Fuel today</span>
          <ChevronRight size={18} className="muted" />
        </div>
        <div className="fuel-row-line">
          <span className="num-strong">{n(d.eaten.kcal)} / {n(t.kcal)} kcal</span>
          {!d.water && t.water_ml > 0 && <span className="muted">{(t.water_ml / 1000).toFixed(1)} L water</span>}
        </div>
        <Meter value={d.eaten.kcal} max={t.kcal} topic="fuel" label="Calories eaten vs target" />
        <div className="fuel-row-line small">
          <span className="muted">Protein {n(d.eaten.protein_g)} / {n(t.protein_g)} g</span>
          <span className="muted">Carbs {n(d.eaten.carbs_g)} / {n(t.carbs_g)} g</span>
        </div>
        <Meter value={d.eaten.protein_g} max={t.protein_g} topic="fuel" label="Protein eaten vs target" />
      </Link>
      <WaterLog date={today} fallback={d.water} compact />
      {tip && <p className="muted small">{tip}</p>}
    </section>
  )
}
