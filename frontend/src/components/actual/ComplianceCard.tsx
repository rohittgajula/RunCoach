import type { Compliance, ComplianceStatus } from '../../lib/types'
import { CheckIcon, CloseIcon } from '../Icons'
import { ScoreRing } from '../ScoreRing'

const VERDICT = (score: number) =>
  score >= 80 ? 'Nailed it' : score >= 60 ? 'Close to plan' : 'Off plan'

function StatusMark({ status }: { status: ComplianceStatus }) {
  return (
    <span className={`check-mark is-${status}`} aria-label={status}>
      {status === 'hit' ? <CheckIcon size={14} /> : status === 'missed' ? <CloseIcon size={14} /> : <span className="check-tilde">~</span>}
    </span>
  )
}

const show = (value: string | number | null) => (value == null || value === '' ? '—' : String(value))

export function ComplianceCard({ compliance }: { compliance: Compliance }) {
  const hits = compliance.checks.filter((c) => c.status === 'hit').length
  return (
    <section className="card compliance">
      <div className="compliance-head">
        <ScoreRing score={compliance.score} size={84} label="score" />
        <div className="grow">
          <p className="card-title">{VERDICT(compliance.score)}</p>
          <p className="muted small">
            {hits} of {compliance.checks.length} checks hit
          </p>
        </div>
      </div>
      <ul className="checks">
        {compliance.checks.map((check) => (
          <li key={check.key} className="check">
            <StatusMark status={check.status} />
            <div className="grow">
              <p className="check-label">{check.label}</p>
              <p className="check-values">
                <span className="muted">{show(check.planned)}</span>
                <span className="muted"> → </span>
                <strong className={`check-actual is-${check.status}`}>{show(check.actual)}</strong>
              </p>
              {check.note && <p className="muted small">{check.note}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
