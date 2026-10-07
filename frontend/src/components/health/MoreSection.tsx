import { Row, RowGroup } from '../Disclose'
import { FlagIcon, HealthIcon, HelpIcon, ReportIcon, ScatterIcon, SparkIcon } from '../Icons'
import { useActiveExperiment, useGoalChip } from '../../lib/r14'

/** R14 §1 Health → More: the less-used sections, one row each. */
export function MoreSection() {
  const exp = useActiveExperiment()
  const goal = useGoalChip()
  const e = exp.data?.experiment
  return (
    <div className="stack">
      <RowGroup title="Your heart & goals">
        <Row to="/health/heart" icon={<HealthIcon size={20} />} title="Heart" sub="How your heart adapts, run by run" />
        <Row to="/health/goals" icon={<FlagIcon size={20} />} title="Goals" sub={goal.data?.text || 'Race time, weight, smoke-free days…'} />
        <Row to="/health/experiments" icon={<SparkIcon size={20} />} title="Experiments" sub={e?.chip || 'Try a change for 1–6 weeks and see what moves'} />
      </RowGroup>
      <RowGroup title="Look deeper">
        <Row to="/health/reports" icon={<ReportIcon size={20} />} title="Reports" sub="Weekly and monthly reports" />
        <Row to="/health/compare" icon={<ScatterIcon size={20} />} title="Compare any two" sub="Sleep vs easy-run HR, drinks vs HRV…" />
        <Row to="/health/guides" icon={<HelpIcon size={20} />} title="Guides" sub="Form, breathing, strength, fuelling, warm-up" />
      </RowGroup>
    </div>
  )
}
