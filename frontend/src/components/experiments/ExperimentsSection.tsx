import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../../lib/AuthContext'
import { addDays, dayMonth, todayISO } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { type Experiment, type ExperimentResult, type ExperimentRule, type ExperimentTemplate } from '../../lib/r14'
import { useExperiment, useExperimentAction, useExperiments, useExperimentTemplates, useStartExperiment } from '../../lib/r14health'
import { BottomSheet } from '../BottomSheet'
import { Disclosure, Row, RowGroup, SectionSummary } from '../Disclose'
import { Field } from '../Field'
import { ChevronRight } from '../Icons'
import { Meter, Pill } from '../Kit'
import { ShareButton } from '../share/ShareButton'
import { Empty, ErrorState, Skeleton } from '../States'

const EMOJI: Record<string, string> = {
  no_alcohol: '🍺', no_late_caffeine: '☕', no_sugar: '🍫', smoke_free: '🚬', bed_by: '🌙', steps: '👟', custom: '🧪',
}

/**
 * R14 §7 Health → More → Experiments: pick a template, run it for 1–6 weeks, see daily
 * adherence, then before vs during (with n) in plain, non-causal words.
 */
export function ExperimentsSection() {
  const list = useExperiments()
  const [params, setParams] = useSearchParams()
  const [template, setTemplate] = useState<ExperimentTemplate | null>(null)
  const openId = Number(params.get('e')) || null
  const open = (id: number | null) => setParams(id ? { e: String(id) } : {}, { replace: !id })

  if (list.isPending) return <section className="card"><Skeleton lines={4} /></section>
  if (list.isError) return <ErrorState message={errorText(list.error, 'Experiments did not load.')} onRetry={() => list.refetch()} />
  if (list.data === null) return <Empty title="Experiments aren’t available yet">Check back after the next update.</Empty>

  const all = list.data ?? []
  const current = all.find((e) => e.status === 'active' || e.status === 'scheduled') ?? null
  const waiting = all.find((e) => e.status !== 'active' && e.status !== 'scheduled' && e.decision == null) ?? null
  const past = all.filter((e) => e !== current && e !== waiting)

  return (
    <div className="stack">
      <SectionSummary
        title={current ? `${current.title}: day ${current.progress?.day ?? 0} of ${current.days}` : 'Try one change, see what it does'}
        facts={[
          'Your own before vs during — same number of days each side.',
          'Days are counted from your logs, watch sleep and steps.',
          'It shows what moved together, not what caused it.',
        ]}
      />

      {current && <ActiveCard e={current} onOpen={() => open(current.id)} />}
      {waiting && <ResultTeaser e={waiting} onOpen={() => open(waiting.id)} />}

      {!current && <TemplatePicker onPick={setTemplate} />}

      {past.length > 0 && (
        <Disclosure id="exp-past" title="Past experiments" sub={`${past.length} finished`}>
          <RowGroup>
            {past.map((e) => (
              <Row
                key={e.id}
                icon={<span aria-hidden="true">{EMOJI[e.kind] ?? '🧪'}</span>}
                title={e.title}
                sub={`${dayMonth(e.start)} – ${dayMonth(e.end)} · ${e.adherence?.pct != null ? `${e.adherence.pct}% kept` : e.status}${e.decision ? ` · ${e.decision === 'keep' ? 'kept it' : 'stopped'}` : ''}`}
                onClick={() => open(e.id)}
              />
            ))}
          </RowGroup>
        </Disclosure>
      )}

      <StartSheet template={template} onClose={() => setTemplate(null)} />
      <ResultSheet id={openId} onClose={() => open(null)} />
    </div>
  )
}

function Strip({ e }: { e: Experiment }) {
  const series = e.adherence?.series ?? []
  if (!series.length) return null
  return (
    <div className="exp-strip" role="img" aria-label={`Daily adherence: ${e.adherence?.days_kept ?? 0} of ${e.adherence?.days_counted ?? 0} days kept`}>
      {series.map((d) => (
        <span key={d.date} className={d.kept == null ? 'is-unknown' : d.kept ? 'is-kept' : 'is-missed'} title={`${dayMonth(d.date)}: ${d.kept == null ? 'no data' : d.kept ? 'kept' : 'not kept'}`} />
      ))}
      {Array.from({ length: Math.max(0, e.days - series.length) }).map((_, i) => <span key={`f${i}`} className="is-future" />)}
    </div>
  )
}

function ActiveCard({ e, onOpen }: { e: Experiment; onOpen: () => void }) {
  const action = useExperimentAction()
  const [confirm, setConfirm] = useState(false)
  const a = e.adherence
  return (
    <section className="card stack-sm exp-card">
      <div className="kit-head">
        <span className="grow kit-title">{EMOJI[e.kind] ?? '🧪'} {e.title}</span>
        {e.status === 'scheduled' ? <Pill>Starts {dayMonth(e.start)}</Pill> : <Pill topic="habits">Day {e.progress?.day ?? 0}/{e.days}</Pill>}
      </div>
      <Meter value={e.progress?.pct ?? 0} max={100} topic="habits" label="Experiment progress" />
      <p className="small">
        {a && a.days_counted > 0 ? <><b>{a.days_kept} of {a.days_counted}</b> days kept{a.pct != null ? ` (${a.pct}%)` : ''}</> : 'No days counted yet.'}
        {a?.today != null && <span className="muted"> · today {a.today ? 'kept so far ✓' : 'not kept'}</span>}
      </p>
      <Strip e={e} />
      <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
        <button type="button" className="see-details" onClick={onOpen}>Results so far <ChevronRight size={16} /></button>
        {confirm ? (
          <span className="row-wrap">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(false)}>Cancel</button>
            <button type="button" className="btn btn-danger btn-sm" disabled={action.isPending} onClick={() => action.mutate({ id: e.id, action: 'stop' })}>Stop now</button>
          </span>
        ) : (
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setConfirm(true)}>Stop</button>
        )}
      </div>
      {action.isError && <p className="bad small">{errorText(action.error, 'Could not stop it.')}</p>}
    </section>
  )
}

function ResultTeaser({ e, onOpen }: { e: Experiment; onOpen: () => void }) {
  return (
    <button type="button" className="card link-row" onClick={onOpen} style={{ width: '100%', textAlign: 'left', border: 0, font: 'inherit', color: 'inherit' }}>
      <span className="link-row-icon" aria-hidden="true">{EMOJI[e.kind] ?? '🧪'}</span>
      <span className="grow">
        <span className="link-row-title">{e.title}: your result is ready</span>
        <span className="link-row-text">{e.adherence?.pct != null ? `${e.adherence.pct}% of days kept` : 'See before vs during'} · keep it or stop?</span>
      </span>
      <ChevronRight size={18} className="muted" />
    </button>
  )
}

function TemplatePicker({ onPick }: { onPick: (t: ExperimentTemplate) => void }) {
  const t = useExperimentTemplates()
  if (t.isPending) return <section className="card"><Skeleton lines={3} /></section>
  if (!t.data?.length) return null
  return (
    <RowGroup title="Start an experiment">
      {t.data.map((x) => (
        <Row key={x.kind} icon={<span aria-hidden="true">{EMOJI[x.kind] ?? '🧪'}</span>} title={x.title} sub={`${x.description} · ${x.default_days} days`} onClick={() => onPick(x)} />
      ))}
    </RowGroup>
  )
}

const HABITS: Array<{ key: NonNullable<ExperimentRule['habit']>; label: string }> = [
  { key: 'alcohol', label: 'Alcohol' }, { key: 'caffeine', label: 'Caffeine' }, { key: 'sugar', label: 'Sugar' }, { key: 'smoke', label: 'Smoking' },
]

function StartSheet({ template, onClose }: { template: ExperimentTemplate | null; onClose: () => void }) {
  return (
    <BottomSheet open={!!template} onClose={onClose} title={template ? `${EMOJI[template.kind] ?? '🧪'} ${template.title}` : ''}>
      {template && <StartForm key={template.kind} t={template} onDone={onClose} />}
    </BottomSheet>
  )
}

function StartForm({ t, onDone }: { t: ExperimentTemplate; onDone: () => void }) {
  const { athlete } = useAuth()
  const start = useStartExperiment()
  const [days, setDays] = useState(t.default_days || 14)
  const [from, setFrom] = useState(todayISO())
  const [habit, setHabit] = useState<NonNullable<ExperimentRule['habit']>>(t.rule.habit ?? 'alcohol')
  const [max, setMax] = useState(String(t.rule.max_per_day ?? 0))
  const [bedtime, setBedtime] = useState(t.rule.bedtime ?? '22:30')
  const [steps, setSteps] = useState(String(t.rule.min_steps ?? 10000))
  const habits = athlete?.private_habit_enabled ? [...HABITS, { key: 'private' as const, label: '🌙 Private' }] : HABITS

  const rule: ExperimentRule | undefined =
    t.kind === 'custom' ? { habit, max_per_day: Number(max) || 0 }
      : t.kind === 'bed_by' ? { bedtime }
        : t.kind === 'steps' ? { min_steps: Number(steps) || 10000 }
          : undefined

  const go = () => start.mutate({ kind: t.kind, days, start: from, ...(rule ? { rule } : {}) }, { onSuccess: onDone })

  return (
    <div className="stack">
      <p className="muted">{t.description}</p>
      {t.kind === 'custom' && (
        <>
          <div className="ci-chips" role="radiogroup" aria-label="Habit">
            {habits.map((h) => (
              <button key={h.key} type="button" role="radio" aria-checked={habit === h.key} className={`ci-chip ${habit === h.key ? 'is-on' : ''}`} onClick={() => setHabit(h.key)}>{h.label}</button>
            ))}
          </div>
          <Field label="At most per day"><input inputMode="numeric" value={max} onChange={(e) => setMax(e.target.value.replace(/[^\d]/g, ''))} /></Field>
        </>
      )}
      {t.kind === 'bed_by' && <Field label="Asleep by"><input type="time" value={bedtime} onChange={(e) => setBedtime(e.target.value)} /></Field>}
      {t.kind === 'steps' && <Field label="Steps a day"><input inputMode="numeric" value={steps} onChange={(e) => setSteps(e.target.value.replace(/[^\d]/g, ''))} /></Field>}
      <Field label={`How long: ${days} days (${Math.round(days / 7 * 10) / 10} weeks)`} hint="Longer = a fairer comparison. Your baseline is the same number of days just before.">
        <input type="range" min={7} max={42} step={1} value={days} onChange={(e) => setDays(Number(e.target.value))} />
      </Field>
      <Field label="Start">
        <input type="date" value={from} min={todayISO()} max={addDays(todayISO(), 14)} onChange={(e) => setFrom(e.target.value)} />
      </Field>
      {start.isError && <p className="bad small">{errorText(start.error, 'Could not start it.')}</p>}
      <button type="button" className="btn btn-primary btn-block" disabled={start.isPending} onClick={go}>
        {start.isPending ? 'Starting…' : 'Start experiment'}
      </button>
      <p className="muted small">One experiment at a time. You can stop it whenever you like.</p>
    </div>
  )
}

function ResultSheet({ id, onClose }: { id: number | null; onClose: () => void }) {
  const q = useExperiment(id)
  const e = q.data
  return (
    <BottomSheet open={id != null} onClose={onClose} title={e ? e.title : 'Experiment'}>
      {id != null && (q.isPending ? <Skeleton lines={5} /> : q.isError || !e ? (
        <ErrorState message={errorText(q.error, 'This experiment did not load.')} onRetry={() => q.refetch()} />
      ) : (
        <ResultBody e={e} result={e.result} onClose={onClose} />
      ))}
    </BottomSheet>
  )
}

const fmt = (v: number | null, unit: string) => (v == null ? '—' : `${Math.round(v * 10) / 10}${unit && unit !== '/5' ? ` ${unit}` : unit}`)

function ResultBody({ e, result: r, onClose }: { e: Experiment; result: ExperimentResult | null; onClose: () => void }) {
  const action = useExperimentAction()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const ended = e.status === 'completed' || e.status === 'stopped'
  return (
    <div className="stack">
      <section className="card stack-sm exp-result">
        <div className="kit-head">
          <span className="grow lbl">{r?.final ? 'Result' : 'So far'} · {dayMonth(e.start)} – {dayMonth(e.end)}</span>
          {(r?.adherence_pct ?? e.adherence?.pct) != null && <Pill topic="habits">{r?.adherence_pct ?? e.adherence?.pct}% kept</Pill>}
        </div>
        {r?.summary && <p className="exp-summary">{r.summary}</p>}
        <Strip e={e} />
      </section>

      {r && r.metrics.length > 0 && (
        <section className="card">
          <div className="exp-table" role="table" aria-label="Before vs during">
            <div role="row" className="exp-row exp-row-head">
              <span role="columnheader">Measure</span><span role="columnheader">Before</span><span role="columnheader">During</span>
            </div>
            {r.metrics.map((m) => (
              <div role="row" key={m.key} className="exp-row">
                <span role="cell">
                  <b className="block">{m.label}</b>
                  <span className={`small ${m.direction === 'better' ? 'good-text' : m.direction === 'worse' ? 'bad' : 'muted'}`}>
                    {!m.enough_data ? 'not enough data'
                      : m.direction === 'better' || m.direction === 'worse'
                        ? `${m.diff != null && m.diff !== 0 ? `${m.diff > 0 ? '▲' : '▼'} ${Math.abs(Math.round(m.diff * 10) / 10)} · ` : ''}${m.direction}`
                        : 'no clear difference'}
                  </span>
                </span>
                <span role="cell">{fmt(m.before, m.unit)}<span className="muted small block">n={m.n_before}</span></span>
                <span role="cell">{fmt(m.during, m.unit)}<span className="muted small block">n={m.n_during}</span></span>
              </div>
            ))}
          </div>
          {r.baseline && <p className="chart-caption" style={{ marginTop: 8 }}>Before = {dayMonth(r.baseline.start)} – {dayMonth(r.baseline.end)} · n = days (or runs) with data.</p>}
        </section>
      )}
      {r?.caveat && <p className="muted small">{r.caveat}</p>}

      {ended && (
        <div className="stack-sm">
          <span className="lbl">Keep it up?</span>
          <div className="row-wrap">
            <button type="button" className={`btn btn-sm ${e.decision === 'keep' ? 'btn-primary' : 'btn-secondary'}`} disabled={action.isPending} onClick={() => action.mutate({ id: e.id, action: 'decide', decision: 'keep' })}>Keep it</button>
            <button type="button" className={`btn btn-sm ${e.decision === 'stop' ? 'btn-primary' : 'btn-secondary'}`} disabled={action.isPending} onClick={() => action.mutate({ id: e.id, action: 'decide', decision: 'stop' })}>Stop</button>
            {r?.share && (
              <ShareButton variant="button" label="Share card" card={() => ({ kind: 'experiment', title: r.share!.title, lines: r.share!.lines })} />
            )}
          </div>
        </div>
      )}
      {action.isError && <p className="bad small">{errorText(action.error, 'Could not save.')}</p>}
      {ended && (
        confirmDelete ? (
          <div className="row-wrap">
            <span className="small grow">Delete this experiment for good?</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmDelete(false)}>Cancel</button>
            <button type="button" className="btn btn-danger btn-sm" disabled={action.isPending} onClick={() => action.mutate({ id: e.id, action: 'delete' }, { onSuccess: onClose })}>Delete</button>
          </div>
        ) : (
          <button type="button" className="link-btn small" onClick={() => setConfirmDelete(true)}>Delete</button>
        )
      )}
    </div>
  )
}
