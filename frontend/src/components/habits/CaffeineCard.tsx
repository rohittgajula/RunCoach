import { useAuth } from '../../lib/AuthContext'
import { useCaffeine } from '../../lib/r13'
import { CardHead, ToneChip } from '../Kit'
import { InfoButton } from '../health/InfoButton'
import type { Freq } from '../health/healthRange'
import { HabitBarChart } from './HabitBarChart'
import { CAFFEINE_TYPES } from './habitUtil'

/**
 * R13 §9 caffeine report: cups per day, by type, late days (after 14:00) and how late
 * caffeine lines up with that night's sleep. Shown when the tile is on or there are logs.
 */
export function CaffeineCard({ range, freq, period }: { range: string; freq: Freq; period: string }) {
  const { athlete } = useAuth()
  const q = useCaffeine(range)
  const r = q.data
  if (!r) return null
  if (!athlete?.caffeine_on_today && r.total === 0) return null
  const points = r.series.map((p) => ({ date: p.date, value: p.count }))
  return (
    <section className={`card stack-sm caffeine-card ${q.isPlaceholderData ? 'is-stale' : ''}`}>
      <CardHead
        title={<span>☕ Caffeine</span>}
        sub={`${r.total} ${r.total === 1 ? 'cup' : 'cups'} · avg ${r.per_day_avg != null ? r.per_day_avg.toFixed(1) : '--'}/day · ${period}`}
      />
      {r.total > 0 ? (
        <>
          <HabitBarChart data={points} color="var(--habits)" unit="cups" height={120} freq={freq} />
          <div className="caffeine-types-row">
            {CAFFEINE_TYPES.filter((t) => (r.by_type[t.key] ?? 0) > 0).map((t) => (
              <span key={t.key} className="pill pill-habits">{t.emoji} {t.label} {r.by_type[t.key]}</span>
            ))}
          </div>
          <p className="small caffeine-late">
            <b>{r.late_days}</b> {r.late_days === 1 ? 'day' : 'days'} with caffeine after {r.late_cutoff}
            <InfoButton k="caffeine_late" />
          </p>
          {r.impact.length > 0 && (
            <div>
              <span className="lbl">Late caffeine vs that night’s sleep</span>
              <ul className="caffeine-impact">
                {r.impact.map((i) => (
                  <li key={i.metric}>
                    <span className="grow">
                      {i.enough_data ? i.sentence : `${i.label}: need at least 4 nights each way (${i.n_late} late, ${i.n_other} not).`}
                    </span>
                    {i.enough_data && (
                      <ToneChip tone={i.direction === 'worse' ? 'bad' : i.direction === 'better' ? 'good' : 'flat'}>
                        {i.direction === 'no_clear_difference' ? '— no clear link' : i.direction === 'worse' ? '▼ worse' : '▲ better'}
                      </ToneChip>
                    )}
                  </li>
                ))}
              </ul>
              {r.caveat && <p className="muted small">{r.caveat}</p>}
            </div>
          )}
        </>
      ) : (
        <p className="muted small">Tap ☕ in Log now each time you have coffee, tea or an energy drink.</p>
      )}
    </section>
  )
}
