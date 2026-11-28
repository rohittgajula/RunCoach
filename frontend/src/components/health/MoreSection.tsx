import { Row, RowGroup } from '../Disclose'
import {
  DietIcon, DropIcon, FlagIcon, HealthIcon, HelpIcon, ProfileIcon,
  ReportIcon, ScatterIcon, SparkIcon,
} from '../Icons'
import { useActiveExperiment, useGoalChip } from '../../lib/r14'

/**
 * R14 §1 Health → More: the less-used sections, one row each.
 *
 * Every `to` here must be a route declared in pages/Insights (or App for /diet) —
 * tests/test_frontend_links.py fails the build otherwise. Three rows in this file
 * pointed at routes 7cf332e had deleted, so tapping them bounced to Overview, and
 * Weight and Blood & urine had routes but no row, so nothing linked to them at all.
 */
export function MoreSection() {
  const exp = useActiveExperiment()
  const goal = useGoalChip()
  const e = exp.data?.experiment
  return (
    <div className="stack">
      <RowGroup title="Your body">
        <Row to="/health/labs" icon={<DropIcon size={20} />} title="Blood & urine" sub="Ferritin, vitamin D, B12 — type them in or upload the report" />
        <Row to="/health/body" icon={<ProfileIcon size={20} />} title="Weight" sub="Your weigh-ins, and where the trend is going" />
        <Row to="/diet" icon={<DietIcon size={20} />} title="Food" sub="What you ate, what to eat, and what to eat before a run" />
        <Row to="/health/sweat" icon={<DropIcon size={20} />} title="Sweat & hydration" sub="Weigh in either side of a run and every drinking figure becomes yours" />
      </RowGroup>
      <RowGroup title="Your heart & goals">
        <Row to="/health/heart" icon={<HealthIcon size={20} />} title="Heart" sub="How your heart adapts, run by run" />
        <Row to="/health/goals" icon={<FlagIcon size={20} />} title="Goals" sub={goal.data?.text || 'Race time, weight, smoke-free days…'} />
        <Row to="/health/experiments" icon={<SparkIcon size={20} />} title="Experiments" sub={e?.chip || 'Try a change for 1–6 weeks and see what moves'} />
      </RowGroup>
      <RowGroup title="Look deeper">
        <Row to="/health/mirror" icon={<ScatterIcon size={20} />} title="Planned vs done" sub="This week's plan against what actually happened — runs, food, sleep, water" />
        <Row to="/health/reports" icon={<ReportIcon size={20} />} title="Reports" sub="Weekly and monthly reports" />
        <Row to="/health/compare" icon={<ScatterIcon size={20} />} title="Compare any two" sub="Sleep vs easy-run HR, drinks vs HRV…" />
        <Row to="/health/guides" icon={<HelpIcon size={20} />} title="Guides" sub="Form, breathing, strength, fuelling, warm-up" />
      </RowGroup>
    </div>
  )
}
