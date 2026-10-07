import { useState } from 'react'
import { parseDate } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useDeletePain, useInjury, type InjuryRisk, type InjuryWatch } from '../../lib/r13'
import { BandageIcon, TrashIcon } from '../Icons'
import { CardHead, Pill } from '../Kit'
import { SeeDetails } from '../Disclose'
import { InfoButton } from '../health/InfoButton'
import type { GlossaryKey } from '../health/glossary'
import { painText, SEVERITY_LABEL } from './BodyMap'
import { PainSheet } from './PainSheet'

const RISK_WORD: Record<InjuryRisk, string> = { low: 'Low risk', moderate: 'Watch', high: 'High risk' }
const FLAG_INFO: Record<string, GlossaryKey> = {
  ramp: 'ramp', long_run_share: 'long_run_share', cadence_drop: 'cadence', gct_balance: 'gct_balance', pain: 'pain_severity',
}
const short = (iso: string) => parseDate(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

export function RiskPill({ risk }: { risk: InjuryRisk }) {
  return <Pill topic={risk === 'high' ? 'bad' : risk === 'moderate' ? 'habits' : 'ok'} solid={risk === 'high'}>{RISK_WORD[risk]}</Pill>
}

/**
 * R13 §3 injury watch: risk, the flags behind it, recent pain, guidance (never a
 * diagnosis) and "Anything hurting?". `whenNotLow` hides it on a low-risk day (Today).
 */
export function InjuryCard({ whenNotLow = false, compact = false }: { whenNotLow?: boolean; compact?: boolean }) {
  const q = useInjury()
  const [open, setOpen] = useState(false)
  const d = q.data
  if (!d) return null
  if (whenNotLow && d.risk === 'low') return null
  return (
    <section className={`card injury-card is-${d.risk}`} aria-label="Injury watch">
      <CardHead
        title={<span className="injury-title"><BandageIcon size={18} /> Injury watch <InfoButton k="injury_risk">{d.note && <p className="muted small">{d.note}</p>}</InfoButton></span>}
        aside={<RiskPill risk={d.risk} />}
      />
      {compact ? (
        <>
          {d.flags[0] && <p className="small">{d.flags[0].text}</p>}
          <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
            <SeeDetails title="Injury watch">
              <section className="card"><InjuryBody d={d} /></section>
            </SeeDetails>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setOpen(true)}>Anything hurting?</button>
          </div>
        </>
      ) : (
        <>
          <InjuryBody d={d} />
          <button type="button" className="btn btn-secondary btn-block injury-btn" onClick={() => setOpen(true)}>
            Anything hurting?
          </button>
        </>
      )}
      <PainSheet open={open} onClose={() => setOpen(false)} />
    </section>
  )
}

function InjuryBody({ d }: { d: InjuryWatch }) {
  const del = useDeletePain()
  if (!d.flags.length && !d.pains.length) {
    return <p className="muted small">Nothing to flag — your load is rising gently and you haven’t reported any pain.</p>
  }
  return (
    <div className="stack-sm">
      {d.flags.length > 0 && (
        <ul className="injury-flags">
          {d.flags.map((f, i) => (
            <li key={`${f.kind}-${i}`} className={`is-${f.level}`}>
              <span className="injury-dot" aria-hidden="true" />
              <span className="grow">
                {f.text}
                {f.since && <span className="muted small"> · since {short(f.since)}</span>}
              </span>
              {FLAG_INFO[f.kind] && <InfoButton k={FLAG_INFO[f.kind]} />}
            </li>
          ))}
        </ul>
      )}
      {d.pains.length > 0 && (
        <div>
          <span className="lbl">Pain you reported (14 days)</span>
          <ul className="injury-pains">
            {d.pains.slice(0, 6).map((p) => (
              <li key={p.id}>
                <span className={`sev-dot sev-${p.severity}`} aria-hidden="true" />
                <span className="grow">{painText(p)} · {SEVERITY_LABEL[p.severity]?.toLowerCase() ?? p.severity}</span>
                <span className="muted small">{short(p.date)}</span>
                <button type="button" className="icon-btn" aria-label={`Delete ${painText(p)} on ${short(p.date)}`} disabled={del.isPending} onClick={() => del.mutate(p.id)}>
                  <TrashIcon size={16} />
                </button>
              </li>
            ))}
          </ul>
          {del.isError && <p className="bad small">{errorText(del.error, 'Could not delete.')}</p>}
        </div>
      )}
      {d.guidance.length > 0 && (
        <ul className="injury-guidance">
          {d.guidance.map((g, i) => <li key={i}>{g}</li>)}
        </ul>
      )}
    </div>
  )
}
