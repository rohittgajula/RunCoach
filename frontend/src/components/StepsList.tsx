import { dur, paceBand } from '../lib/format'
import type { Step } from '../lib/types'

const STEP_NAME: Record<string, string> = {
  warmup: 'Warm up', run: 'Run', walk: 'Walk', stride: 'Stride', recovery: 'Recovery',
  cooldown: 'Cool down', interval: 'Interval',
}

/** "20s" under a minute, "3:30" for part minutes. */
export const clock = (seconds: number): string => {
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Right-hand duration: whole minutes stay "5m" / "1h 5m", part minutes become m:ss. */
export const stepDuration = (seconds: number): string => {
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  return s % 60 === 0 ? dur(s) : clock(s)
}

const stepName = (step: Step) => STEP_NAME[step.kind] || step.kind

/** Run/walk blocks get "Run 3:30" from the duration (old plans carry "Run 3.7m"); other steps keep their label. */
const singleLabel = (step: Step) =>
  step.kind === 'run' || step.kind === 'walk' || !step.label ? `${stepName(step)} ${clock(step.duration_s)}` : step.label

type Row =
  | { type: 'single'; step: Step; count: number }
  | { type: 'pair'; a: Step; b: Step; count: number }

const same = (a: Step, b: Step) =>
  a.kind === b.kind && a.duration_s === b.duration_s && a.intensity === b.intensity && a.label === b.label

/**
 * Collapse repeats so the list stays readable: A,B,A,B,A,B → "3 × (Run 3:30 · Walk 3:00)",
 * A,A,A → "3 × Stride 20s".
 */
export function groupSteps(steps: Step[]): Row[] {
  const rows: Row[] = []
  let i = 0
  while (i < steps.length) {
    const a = steps[i]
    const b = steps[i + 1]
    if (b && !same(a, b)) {
      let count = 1
      while (
        steps[i + count * 2] && steps[i + count * 2 + 1] &&
        same(steps[i + count * 2], a) && same(steps[i + count * 2 + 1], b)
      ) count++
      if (count > 1) {
        rows.push({ type: 'pair', a, b, count })
        i += count * 2
        continue
      }
    }
    let run = 1
    while (steps[i + run] && same(steps[i + run], a)) run++
    rows.push({ type: 'single', step: a, count: run })
    i += run
  }
  return rows
}

function target(step: Step) {
  const hr = step.hr_min || step.hr_max ? `${step.hr_min ?? ''}–${step.hr_max ?? ''} bpm` : ''
  return [paceBand(step.pace_min_s, step.pace_max_s), hr].filter(Boolean).join(' · ') || step.intensity
}

export function StepsList({ steps }: { steps: Step[] }) {
  if (!steps.length) return null
  return (
    <ul className="steps">
      {groupSteps(steps).map((row, index) => {
        if (row.type === 'pair') {
          const { a, b, count } = row
          // The hard half of the pair carries the target (run, stride, interval).
          const lead = b.intensity !== 'walk' && a.intensity === 'walk' ? b : a
          return (
            <li key={index} className="step">
              <span className="step-swatch step-swatch-pair">
                <span className={`wbar-${a.intensity}`} />
                <span className={`wbar-${b.intensity}`} />
              </span>
              <div className="step-main">
                <p className="step-name">
                  <span className="step-count">{count} × </span>
                  ({stepName(a)} {clock(a.duration_s)} · {stepName(b)} {clock(b.duration_s)})
                </p>
                <p className="step-target">{target(lead)}</p>
              </div>
              <span className="step-dur">{stepDuration(count * (a.duration_s + b.duration_s))}</span>
            </li>
          )
        }
        const { step, count } = row
        return (
          <li key={index} className="step">
            <span className={`step-swatch wbar-${step.intensity}`} />
            <div className="step-main">
              <p className="step-name">
                {count > 1 && <span className="step-count">{count} × </span>}
                {singleLabel(step)}
              </p>
              <p className="step-target">{target(step)}</p>
            </div>
            <span className="step-dur">{stepDuration(step.duration_s)}</span>
          </li>
        )
      })}
    </ul>
  )
}
