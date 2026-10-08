import { pace } from '../../lib/format'
import { useAuth } from '../../lib/AuthContext'
import type { EditModel } from '../../lib/r16edit'
import type { Target } from './editModel'
import { NumStepper } from './Steppers'

export type HrBounds = {
  rest: number
  max: number
  ceiling: number | null
  zones: Array<{ name: string; label: string; low: number; high: number }>
  easy: [number, number]
  easyPace: [number, number]
}

/**
 * HR limits from GET /workouts/{id}/edit/ (`limits`, `hr`, `pace`), zones from the
 * athlete (Settings / Health) as hints.
 */
export function useHrBounds(model?: Pick<EditModel, 'limits' | 'hr' | 'pace'> | null): HrBounds {
  const { athlete } = useAuth()
  const z = athlete?.zones
  const rest = model?.limits.hr_min ?? z?.resting_hr ?? athlete?.resting_hr ?? 40
  const max = model?.limits.hr_max ?? z?.max_hr ?? athlete?.max_hr ?? 200
  return {
    rest,
    max,
    ceiling: model?.hr.ceiling ?? athlete?.hr_ceiling ?? null,
    zones: (z?.zones ?? []).map((x) => ({ name: x.name, label: x.label, low: x.low, high: x.high })),
    easy: [model?.hr.easy_low ?? athlete?.hr_easy_min ?? Math.round(rest + (max - rest) * 0.6), model?.hr.easy_high ?? athlete?.hr_easy_max ?? Math.round(rest + (max - rest) * 0.7)],
    easyPace: [model?.pace.easy_low ?? athlete?.easy_pace_min ?? 390, model?.pace.easy_high ?? athlete?.easy_pace_max ?? 450],
  }
}

/** Two bpm steppers + the athlete's zones as tap-to-use hints. */
export function HrRange({
  low, high, onChange, bounds,
}: { low: number; high: number; onChange: (low: number, high: number) => void; bounds: HrBounds }) {
  const over = bounds.ceiling != null && high > bounds.ceiling
  return (
    <div className="ed-range">
      <div className="ed-range-row">
        <span className="ed-range-lbl">From</span>
        <NumStepper label="Lowest heart rate" value={low} min={bounds.rest} max={high} unit="bpm" onChange={(v) => onChange(v, high)} />
      </div>
      <div className="ed-range-row">
        <span className="ed-range-lbl">To</span>
        <NumStepper label="Highest heart rate" value={high} min={low} max={bounds.max} unit="bpm" onChange={(v) => onChange(low, v)} />
      </div>
      {bounds.zones.length > 0 && (
        <div className="ed-zones" role="group" aria-label="Your zones">
          {bounds.zones.filter((z) => z.high > bounds.rest && z.low < bounds.max).map((z) => {
            const on = z.low === low && z.high === high
            return (
              <button key={z.name} type="button" className={`ed-zone ${on ? 'is-on' : ''}`} aria-pressed={on} onClick={() => onChange(Math.max(bounds.rest, z.low), Math.min(bounds.max, z.high))} title={z.label}>
                <b>{z.name}</b> {z.low}–{z.high}
              </button>
            )
          })}
        </div>
      )}
      {over && <p className="ed-hint is-warn">Above your easy ceiling ({bounds.ceiling} bpm).</p>}
    </div>
  )
}

/** Pace range in s/km: fast edge first. */
export function PaceRange({ low, high, onChange }: { low: number; high: number; onChange: (low: number, high: number) => void }) {
  return (
    <div className="ed-range">
      <div className="ed-range-row">
        <span className="ed-range-lbl">Fastest</span>
        <NumStepper label="Fastest pace" value={low} min={150} max={high} step={5} format={pace} unit="/km" onChange={(v) => onChange(v, high)} />
      </div>
      <div className="ed-range-row">
        <span className="ed-range-lbl">Slowest</span>
        <NumStepper label="Slowest pace" value={high} min={low} max={1200} step={5} format={pace} unit="/km" onChange={(v) => onChange(low, v)} />
      </div>
    </div>
  )
}

export const targetText = (t: Target) =>
  t.type === 'hr' ? `HR ${t.low}–${t.high}` : t.type === 'pace' ? `${pace(t.low)}–${pace(t.high)} /km` : t.type === 'none' ? 'No target' : ''

const TARGET_LABEL: Record<Target['type'], string> = { auto: 'Auto', hr: 'HR', pace: 'Pace', none: 'None' }

/** Auto · HR range · Pace range · None, then the matching range editor. */
export function TargetPicker({ target, onChange, bounds }: { target: Target; onChange: (t: Target) => void; bounds: HrBounds }) {
  const pick = (type: Target['type']) => {
    if (type === target.type) return
    if (type === 'hr') onChange({ type: 'hr', low: bounds.easy[0], high: bounds.easy[1] })
    else if (type === 'pace') onChange({ type: 'pace', low: bounds.easyPace[0], high: bounds.easyPace[1] })
    else onChange({ type })
  }
  return (
    <div className="ed-target">
      <span className="ed-range-lbl">Target on the watch</span>
      <div className="segmented segmented-full segmented-sm" role="radiogroup" aria-label="Target on the watch">
        {(['auto', 'hr', 'pace', 'none'] as const).map((t) => (
          <button key={t} type="button" role="radio" aria-checked={target.type === t} className={`segmented-option ${target.type === t ? 'is-active' : ''}`} onClick={() => pick(t)}>
            {TARGET_LABEL[t]}
          </button>
        ))}
      </div>
      {target.type === 'auto' && <p className="ed-hint">Your usual band for this kind of step.</p>}
      {target.type === 'none' && <p className="ed-hint">No alerts — run by feel.</p>}
      {target.type === 'hr' && <HrRange low={target.low} high={target.high} bounds={bounds} onChange={(low, high) => onChange({ type: 'hr', low, high })} />}
      {target.type === 'pace' && <PaceRange low={target.low} high={target.high} onChange={(low, high) => onChange({ type: 'pace', low, high })} />}
    </div>
  )
}
