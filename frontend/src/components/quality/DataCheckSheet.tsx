import { errorText } from '../../lib/queries'
import { qualityChipText, type ActivityQuality, type HrUse } from '../../lib/r17'
import { usePatchQuality, useQualitySeries } from '../../lib/r17lazy'
import { BottomSheet } from '../BottomSheet'
import { InfoButton } from '../health/InfoButton'
import { HrMaskChart } from './HrMaskChart'
import '../../styles/r17lazy.css'

const KIND: Record<string, string> = {
  hr_cadence_lock: 'Wrist HR locked onto your step rate',
  hr_spike: 'Sudden heart-rate spike not matched by your pace',
  hr_flatline: 'Heart rate flat-lined',
  hr_above_max: 'Heart rate above your max',
  gps_speed: 'GPS jumped (impossible speed)',
  gps_teleport: 'GPS teleported between points',
  gps_drift: 'GPS drifted while you stood still',
  pause_mismarked: 'Pause not marked by the watch',
}
const AFFECTED: Record<string, string> = {
  avg_hr: 'average HR', hr_drift: 'HR drift', time_in_zone: 'time in zones', heart_adaptation: 'heart adaptation', pace: 'pace',
  distance: 'distance', splits: 'splits', route: 'the map', records: 'personal records',
}
const FIX: Record<string, string> = { interpolated: 'smoothed over', masked: 'ignored', flagged: 'noted only' }
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

function Seg<T extends string>({ value, options, onChange, label, disabled }: { value: T; options: Array<[T, string]>; onChange: (v: T) => void; label: string; disabled?: boolean }) {
  return (
    <div className="seg2" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} disabled={disabled} onClick={() => value !== v && onChange(v)}>{text}</button>
      ))}
    </div>
  )
}

/**
 * R17 §2: what the data check found on one run, the HR trace with fixed parts greyed,
 * and the athlete's choices — cleaned or raw HR, keep or exclude from trends. Nothing
 * is excluded unless they choose it.
 */
export default function DataCheckSheet({
  open, onClose, activityId, quality,
}: { open: boolean; onClose: () => void; activityId: number; quality: ActivityQuality }) {
  const series = useQualitySeries(activityId, open)
  const patch = usePatchQuality(activityId)
  const q = patch.data?.quality ?? series.data?.quality ?? quality
  const excluded = q.decision === 'exclude'
  const use: HrUse = q.use ?? 'cleaned'
  const flags = q.flags ?? []
  const hr = (series.data?.series ?? []).map((p) => ({ t: p.t, raw: p.hr_raw, clean: p.hr_clean, fixed: p.fixed }))
  const hrFlags = flags.filter((f) => f.kind.startsWith('hr_'))
  const fixedSpans = hr.length > 1 ? spansOf(hr) : []

  return (
    <BottomSheet open={open} onClose={onClose} title="Data check">
      <div className="stack">
        <div className="dq-score">
          <span className="dq-score-num">{q.score != null ? Math.round(q.score) : '--'}</span>
          <span className="grow">
            <span className="lbl title-info">Data quality<InfoButton title="Data quality" label="What is data quality?">
              {q.info ? <p>{q.info}</p> : <>
                <p>A 0–100 check of how trustworthy this run’s watch data is. Wrist heart rate can lock onto your step rate or spike, and GPS can jump.</p>
                <p>We fix small glitches (the raw data is always kept). If a lot looks wrong we may suggest leaving the run out of your trends — only you decide.</p>
              </>}
            </InfoButton></span>
            <span className="block small">{qualityChipText(q)}</span>
          </span>
        </div>
        {q.summary && <p>{q.summary}</p>}

        {q.suggestion === 'exclude' && !q.decision && (
          <p className="ill-warn">
            <b>Suggestion: leave this run out of trends{q.suggestion_reason ? ` — ${q.suggestion_reason[0].toLowerCase()}${q.suggestion_reason.slice(1)}` : ''}.</b>{' '}
            It’s still counted until you choose. Sometimes the data is right — your call.
          </p>
        )}
        {q.use_suggestion === 'cleaned' && !q.use_choice && (
          <p className="ill-warn">Suggestion: use the cleaned heart rate for this run. Right now the raw reading is used.</p>
        )}

        {flags.length > 0 ? (
          <section>
            <h3 className="lbl" style={{ marginBottom: 8 }}>What we fixed</h3>
            <ul className="dq-list">
              {flags.map((f, i) => (
                <li key={i}>
                  <span className={`dq-dot is-${f.severity}`} aria-hidden="true" />
                  <span>
                    {f.text || KIND[f.kind] || f.kind.replace(/_/g, ' ')}
                    <span className="muted small block">{mmss(f.start_s)}–{mmss(f.end_s)}{FIX[f.fix] ? ` · ${FIX[f.fix]}` : ''}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : <p className="muted">Nothing looked wrong — heart rate and GPS passed every check.</p>}

        {series.isPending && open && <p className="muted small">Loading heart-rate trace…</p>}
        {hr.length > 1 && <HrMaskChart points={hr} flags={fixedSpans.length ? fixedSpans : hrFlags} />}
        {!!q.affected?.length && <p className="muted small">Affects: {q.affected.map((a) => AFFECTED[a] ?? a.replace(/_/g, ' ')).join(', ')}.</p>}

        {hrFlags.length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            <span className="lbl">Heart rate to use</span>
            <Seg<HrUse> label="Heart rate to use" value={use} disabled={patch.isPending}
              options={[['cleaned', 'Use cleaned HR'], ['raw', 'Use raw HR']]}
              onChange={(v) => patch.mutate({ use: v })} />
            {q.use_choice && <button type="button" className="btn btn-ghost btn-sm" onClick={() => patch.mutate({ use: null })}>Back to the default</button>}
          </div>
        )}
        <div className="stack" style={{ gap: 6 }}>
          <span className="lbl">In trends &amp; progress</span>
          <Seg<'keep' | 'exclude'> label="Include in trends" value={excluded ? 'exclude' : 'keep'} disabled={patch.isPending}
            options={[['keep', 'Keep'], ['exclude', 'Exclude']]}
            onChange={(v) => patch.mutate({ decision: v === 'keep' ? 'include' : 'exclude' })} />
          <span className="muted small">{excluded ? 'Excluded by you — still in your history, just not in trends, PRs or comparisons.' : 'This run counts in your trends.'}</span>
        </div>
        {patch.isError && <p className="bad small">{errorText(patch.error, 'Couldn’t save. Try again.')}</p>}
        <p className="muted small">Your original watch data is never changed.</p>
      </div>
    </BottomSheet>
  )
}

/** Grey spans from the series' `fixed` buckets. */
function spansOf(pts: Array<{ t: number; fixed: boolean }>) {
  const out: Array<{ kind: string; start_s: number; end_s: number; severity: 'low'; fix: 'masked'; text: string }> = []
  let from: number | null = null
  pts.forEach((p, i) => {
    const next = pts[i + 1]?.t ?? p.t
    if (p.fixed && from == null) from = p.t
    if (from != null && (!p.fixed || i === pts.length - 1)) {
      out.push({ kind: 'hr_fixed', start_s: from, end_s: p.fixed ? next : p.t, severity: 'low', fix: 'masked', text: '' })
      from = null
    }
  })
  return out
}
