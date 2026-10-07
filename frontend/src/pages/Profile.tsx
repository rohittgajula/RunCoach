import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight, MoreHIcon } from '../components/Icons'
import { PlanTimeline } from '../components/PlanTimeline'
import { useShell } from '../components/Shell'
import { Sparkline } from '../components/Sparkline'
import { ErrorState, Skeleton } from '../components/States'
import { FitnessSheet, STATUS_LABEL, type FitnessView } from '../components/profile/FitnessSheet'
import { MemorySheet } from '../components/profile/MemorySheet'
import { MetricSheet } from '../components/profile/MetricSheet'
import { PlanDetailSheet } from '../components/profile/PlanDetailSheet'
import { RacesCard } from '../components/profile/RacesCard'
import { dur, pace } from '../lib/format'
import { errorText, useProfileSummary } from '../lib/queries'
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
  const s = summary.data

  return (
    <>

      {summary.isPending && (
        <>
          <section className="card"><Skeleton lines={4} /></section>
          <div className="grid-2-cards">
            <section className="card"><Skeleton lines={3} /></section>
            <section className="card"><Skeleton lines={3} /></section>
          </div>
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
            <div className="metric-grid metric-grid-sep">
              <Metric label="HRV" value={s.wellness?.hrv_ms != null ? String(Math.round(s.wellness.hrv_ms)) : '--'} unit="ms" />
              <Metric
                label="RHR"
                value={s.wellness?.resting_hr != null ? String(Math.round(s.wellness.resting_hr)) : '--'}
                unit="bpm"
                onClick={() => setMetric('resting_hr')}
              />
              <Metric label="Sleep" value={s.wellness?.sleep_s ? dur(s.wellness.sleep_s) : '--'} />
            </div>
          </section>

          <div className="grid-2-cards">
            <button type="button" className="card mini-card" onClick={() => setFitnessView('status')}>
              <span className="mini-card-label">Training Status</span>
              <span className="mini-card-value">{STATUS_LABEL[s.fitness.status] ?? s.fitness.status}</span>
              <Sparkline values={s.status_spark} color="var(--faint)" />
            </button>
            <button type="button" className="card mini-card" onClick={() => setFitnessView('fitness')}>
              <span className="mini-card-label">Fitness</span>
              <span className="mini-card-value">{s.fitness.value != null ? Math.round(s.fitness.value) : '--'}</span>
              <Sparkline values={s.fitness.spark} area />
            </button>
          </div>

          {s.active_plan ? (
            <section className="card is-tappable" onClick={() => setPlanId(s.active_plan!.id)} role="button" tabIndex={0}>
              <div className="card-head">
                <div>
                  <h2 className="card-title card-title-lg">{s.active_plan.name}</h2>
                  <p className="muted">{s.active_plan.phase_count} phases</p>
                </div>
                <ChevronRight className="muted" />
              </div>
              <PlanTimeline phases={s.active_plan.phases} currentPhaseId={s.active_plan.current_phase_id} variant="compact" />
            </section>
          ) : (
            <section className="card banner">
              <p className="banner-title">No active plan</p>
              <p className="muted small">Ask the coach to build one around your race or goal.</p>
              <button type="button" className="btn btn-primary" onClick={() => navigate('/chat/new', { state: { prompt: BUILD_PLAN_PROMPT } })}>
                Ask the coach
              </button>
            </section>
          )}

          <RacesCard />

          <button type="button" className="card link-card" onClick={() => setMemoryOpen(true)}>
            <span>
              <span className="card-title card-title-lg block">Memory</span>
              <span className="muted">
                {s.memory_count ? `${s.memory_count} fact${s.memory_count === 1 ? '' : 's'} remembered from your chats` : 'Facts remembered from your chats'}
              </span>
            </span>
            <ChevronRight className="muted" />
          </button>
        </>
      )}

      <MetricSheet kind={metric} onClose={() => setMetric(null)} />
      <FitnessSheet view={fitnessView} onClose={() => setFitnessView(null)} />
      <PlanDetailSheet planId={planId} onClose={() => setPlanId(null)} />
      <MemorySheet open={memoryOpen} onClose={() => setMemoryOpen(false)} />
    </>
  )
}
