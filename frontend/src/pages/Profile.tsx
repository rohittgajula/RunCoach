import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ActivityIcon, ChevronRight, FlagIcon, MoreHIcon, PlanIcon, SparkIcon } from '../components/Icons'
import { Row, RowGroup } from '../components/Disclose'
import { useShell } from '../components/Shell'
import { ErrorState, Skeleton } from '../components/States'
import { FitnessSheet, STATUS_LABEL, type FitnessView } from '../components/profile/FitnessSheet'
import { MemorySheet } from '../components/profile/MemorySheet'
import { MetricSheet } from '../components/profile/MetricSheet'
import { PlanDetailSheet } from '../components/profile/PlanDetailSheet'
import { dur, pace } from '../lib/format'
import { errorText, useProfileSummary, useRaces } from '../lib/queries'
import type { MetricKind } from '../lib/types'
import { BUILD_PLAN_PROMPT } from '../lib/prompts'

function Metric({
  label, value, unit, onClick,
}: { label: string; value: string; unit?: string; onClick?: () => void }) {
  const body = (
    <>
      <span className="metric-label">{label}</span>
      <span className={`metric-value ${value.length > 6 ? 'metric-value-sm' : ''}`}>
        {value}
        {unit && <small>{unit}</small>}
      </span>
    </>
  )
  return onClick ? (
    <button type="button" className="metric-cell is-tappable" onClick={onClick}>
      {body}
    </button>
  ) : (
    <div className="metric-cell">{body}</div>
  )
}

/** Me: who you are, fitness, plan, races, memory (the pre-R10 Profile tab). */
export function ProfileCards() {
  const { openSettings } = useShell()
  const navigate = useNavigate()
  const summary = useProfileSummary()
  const [metric, setMetric] = useState<MetricKind | null>(null)
  const [fitnessView, setFitnessView] = useState<FitnessView | null>(null)
  const [planId, setPlanId] = useState<number | null>(null)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [menu, setMenu] = useState(false)
  const [more, setMore] = useState(false)
  const s = summary.data

  return (
    <>

      {summary.isPending && (
        <>
          <section className="card"><Skeleton lines={4} /></section>
          <section className="card"><Skeleton lines={3} /></section>
        </>
      )}
      {summary.isError && !s && (
        <ErrorState message={errorText(summary.error, 'Your profile did not load.')} onRetry={() => summary.refetch()} />
      )}

      {s && (
        <>
          <section className="card athlete">
            <div className="card-head">
              <h2 className="card-title">Your numbers</h2>
              <div className="menu-wrap">
                <button type="button" className="icon-btn" aria-label="More" onClick={() => setMenu(!menu)}>
                  <MoreHIcon />
                </button>
                {menu && (
                  <div className="menu" role="menu">
                    <button type="button" role="menuitem" onClick={() => { setMenu(false); setMetric('max_hr') }}>Max HR history</button>
                    <button type="button" role="menuitem" onClick={() => { setMenu(false); openSettings() }}>Edit profile</button>
                  </div>
                )}
              </div>
            </div>
            <div className="metric-grid">
              <Metric
                label="Threshold Pace"
                value={s.athlete.threshold_pace_s ? pace(s.athlete.threshold_pace_s) : '--'}
                unit="min/km"
                onClick={() => setMetric('threshold_pace')}
              />
              <Metric
                label="Weight"
                value={s.athlete.weight_kg != null ? s.athlete.weight_kg.toFixed(1) : '--'}
                unit="kg"
                onClick={() => setMetric('weight')}
              />
              <Metric
                label="Easy pace"
                value={s.athlete.easy_pace_min && s.athlete.easy_pace_max ? `${pace(s.athlete.easy_pace_min)}–${pace(s.athlete.easy_pace_max)}` : '--'}
              />
            </div>
            {more && <div className="metric-grid metric-grid-sep">
              <Metric label="HRV" value={s.wellness?.hrv_ms != null ? String(Math.round(s.wellness.hrv_ms)) : '--'} unit="ms" />
              <Metric
                label="RHR"
                value={s.wellness?.resting_hr != null ? String(Math.round(s.wellness.resting_hr)) : '--'}
                unit="bpm"
                onClick={() => setMetric('resting_hr')}
              />
              <Metric label="Sleep" value={s.wellness?.sleep_s ? dur(s.wellness.sleep_s) : '--'} />
            </div>}
            <button type="button" className="see-details" aria-expanded={more} onClick={() => setMore(!more)}>
              {more ? 'Fewer numbers' : 'HRV, resting HR, sleep'} <ChevronRight size={16} />
            </button>
          </section>

          <RowGroup title="Training">
            {s.active_plan ? (
              <Row
                icon={<PlanIcon size={20} />}
                title={s.active_plan.name}
                sub={`${s.active_plan.phase_count} phases · tap for the timeline`}
                onClick={() => setPlanId(s.active_plan!.id)}
              />
            ) : (
              <Row
                icon={<PlanIcon size={20} />}
                title="No active plan"
                sub="Ask the coach to build one around your race or goal"
                onClick={() => navigate('/chat/new', { state: { prompt: BUILD_PLAN_PROMPT } })}
              />
            )}
            <RacesRow />
            <Row
              icon={<ActivityIcon size={20} />}
              title="Training status & fitness"
              sub={`${STATUS_LABEL[s.fitness.status] ?? s.fitness.status ?? '—'} · fitness ${s.fitness.value != null ? Math.round(s.fitness.value) : '--'}`}
              onClick={() => setFitnessView('status')}
            />
            <Row
              icon={<SparkIcon size={20} />}
              title="Memory"
              sub={s.memory_count ? `${s.memory_count} fact${s.memory_count === 1 ? '' : 's'} remembered from your chats` : 'Facts remembered from your chats'}
              onClick={() => setMemoryOpen(true)}
            />
          </RowGroup>
        </>
      )}

      <MetricSheet kind={metric} onClose={() => setMetric(null)} />
      <FitnessSheet view={fitnessView} onClose={() => setFitnessView(null)} />
      <PlanDetailSheet planId={planId} onClose={() => setPlanId(null)} />
      <MemorySheet open={memoryOpen} onClose={() => setMemoryOpen(false)} />
    </>
  )
}

/** Me → Races row: the next race (or a prompt to add one). Full list on /me/races. */
function RacesRow() {
  const races = useRaces()
  const today = new Date().toISOString().slice(0, 10)
  const next = (races.data ?? []).filter((r) => r.date >= today).sort((a, b) => a.date.localeCompare(b.date))[0]
  const sub = next
    ? `${next.name} · ${new Date(next.date + 'T00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} · ${next.distance_km} km`
    : 'Add a race — the plan builds towards it'
  return <Row to="/me/races" icon={<FlagIcon size={20} />} title="Races & race plans" sub={sub} />
}
