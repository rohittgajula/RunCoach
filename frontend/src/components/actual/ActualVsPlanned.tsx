import { dur, pace } from '../../lib/format'
import type { Step, WorkoutActual, Zone } from '../../lib/types'
import { clock } from '../StepsList'
import { WorkoutBar } from '../WorkoutBar'

const kmShort = (m: number | null) => (m == null ? '--' : (m / 1000).toFixed(2))

function Stat({ label, value, unit, sub }: { label: string; value: string; unit?: string; sub?: string }) {
  return (
    <div className="avp-stat">
      <span className="stat-label">{label}</span>
      <span className="avp-value">
        {value}
        {unit && <small> {unit}</small>}
      </span>
      {sub && <span className="muted small">{sub}</span>}
    </div>
  )
}

const longest = (s: number | null) => (s == null ? '--' : s >= 3600 ? dur(s) : clock(s))

const ZONES: Zone[] = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5']

function ZoneBar({ zones }: { zones: Partial<Record<Zone, number>> }) {
  const total = ZONES.reduce((sum, z) => sum + (zones[z] ?? 0), 0)
  if (!total) return null
  return (
    <div className="zones">
      <div className="zone-bar" role="img" aria-label="Time in heart-rate zones">
        {ZONES.map((z) => {
          const share = (zones[z] ?? 0) / total
          return share > 0 ? <span key={z} className={`zone-${z.toLowerCase()}`} style={{ flexGrow: share }} /> : null
        })}
      </div>
      <div className="zone-legend">
        {ZONES.map((z) => (
          <span key={z}>
            <i className={`zone-${z.toLowerCase()}`} /> {z} {Math.round(((zones[z] ?? 0) / total) * 100)}%
          </span>
        ))}
      </div>
    </div>
  )
}

/** R7 §3: "Time above cap: 6 min (22 %)", red over 20 %. */
function TimeAboveCap({ actual }: { actual: WorkoutActual }) {
  const seconds = actual.time_above_cap_s
  if (seconds == null) return null
  const pct = actual.time_above_cap_pct ?? (actual.duration_s ? (seconds / actual.duration_s) * 100 : null)
  return (
    <p className={`avp-cap ${pct != null && pct > 20 ? 'is-over' : ''}`}>
      Time above cap: <b>{Math.round(seconds / 60)} min</b>
      {pct != null && <> ({Math.round(pct)} %)</>}
    </p>
  )
}

/** Planned bar above actual bar, then the numbers that matter for run/walk training. */
export function ActualVsPlanned({
  planned, plannedDuration, actual,
}: { planned?: Step[] | null; plannedDuration?: number; actual: WorkoutActual }) {
  return (
    <section className="detail-section">
      <h3>{planned ? 'Actual vs planned' : 'What you ran'}</h3>
      <div className="card avp">
        {planned && (
          <div className="avp-bar">
            <span className="avp-bar-label">Planned</span>
            <WorkoutBar steps={planned} height={44} compact />
          </div>
        )}
        <div className="avp-bar">
          <span className="avp-bar-label">Actual</span>
          <WorkoutBar steps={actual.steps} height={44} compact />
        </div>
        <div className="avp-grid">
          <Stat
            label="Duration"
            value={dur(actual.duration_s)}
            sub={plannedDuration ? `plan ${dur(plannedDuration)}` : undefined}
          />
          <Stat
            label="Run"
            value={kmShort(actual.run_distance_m)}
            unit="km"
            sub={actual.run_fraction != null ? `${Math.round(actual.run_fraction * 100)}% running` : undefined}
          />
          <Stat label="Walk" value={kmShort(actual.walk_distance_m)} unit="km" />
          <Stat label="Longest run" value={longest(actual.longest_run_s)} sub="continuous" />
          <Stat label="Avg HR" value={actual.avg_hr != null ? String(Math.round(actual.avg_hr)) : '--'} unit="bpm" sub={actual.max_hr ? `max ${Math.round(actual.max_hr)}` : undefined} />
          <Stat label="Cadence" value={actual.avg_cadence_spm != null ? String(Math.round(actual.avg_cadence_spm)) : '--'} unit="spm" />
          <Stat label="Run pace" value={pace(actual.avg_pace_s_per_km)} unit="/km" />
        </div>
        {actual.time_in_zone && <ZoneBar zones={actual.time_in_zone} />}
        <TimeAboveCap actual={actual} />
        {(actual.avg_stride_length_m != null || actual.avg_ground_contact_ms != null || actual.training_effect_aerobic != null) && (
          <p className="muted small avp-extra">
            {[
              actual.avg_stride_length_m != null && `Stride ${actual.avg_stride_length_m.toFixed(2)} m`,
              actual.avg_ground_contact_ms != null && `Contact ${Math.round(actual.avg_ground_contact_ms)} ms`,
              actual.avg_vertical_oscillation_cm != null && `Bounce ${actual.avg_vertical_oscillation_cm.toFixed(1)} cm`,
              actual.training_effect_aerobic != null && `Aerobic TE ${actual.training_effect_aerobic.toFixed(1)}`,
            ].filter(Boolean).join(' · ')}
          </p>
        )}
      </div>
    </section>
  )
}
