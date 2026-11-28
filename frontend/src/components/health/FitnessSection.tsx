import { Disclosure, Row, RowGroup } from '../Disclose'
import { HealthIcon } from '../Icons'
import { dayMonth, duration, pace } from '../../lib/format'
import { errorText, useHealthFitness, useInsights } from '../../lib/queries'
import type { AthleteZones, HealthFitness, RacePred } from '../../lib/types'
import { ChartFrame } from '../ChartFrame'
import { CardHead, Delta, MetricTile, Pill } from '../Kit'
import { MetricChart } from '../MetricChart'
import { Sparkline } from '../Sparkline'
import { Empty, ErrorState, Skeleton } from '../States'
import { InfoButton } from './InfoButton'
import { bucket, periodCaption, useHealthPeriod, withApiPeriod, type Period } from './healthRange'
import { TrainingStatusCard } from './TrainingStatusCard'

const inWords = (p: Period) => (p.selection.kind === 'preset' ? `in ${p.selection.range === '1y' ? 'a year' : p.long}` : 'in this period')
const one = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1))

/** Health → Fitness: VO2max trend, fitness age, endurance, race times, LT + zones, status. */
export function FitnessSection() {
  const { period: chosen } = useHealthPeriod()
  const fitness = useHealthFitness(chosen.params)
  const insights = useInsights('6m')
  const f = fitness.data
  const period = withApiPeriod(chosen, f?.period)

  if (fitness.isPending) return <div className="stack"><section className="card"><Skeleton height={200} /></section><Skeleton lines={4} /></div>
  if (fitness.isError && !f) return <ErrorState message={errorText(fitness.error, 'Fitness did not load.')} onRetry={() => fitness.refetch()} />

  // Endpoint not deployed: fall back to the R6 numbers so the page is never blank.
  const vo2 = f?.vo2max ?? (insights.data?.vo2max
    ? { current: insights.data.vo2max.value, change: null, series: [] }
    : null)
  const hasAnything = !!(vo2?.current != null || f?.fitness_age?.current != null || f?.endurance_score?.current != null || f?.race_predictions?.current || f?.lactate_threshold)

  return (
    <div className={`stack ${fitness.isPlaceholderData ? 'is-stale' : ''}`}>
      {vo2?.current != null && <Vo2Card vo2={vo2} period={period} />}
      <AgeEndurance f={f} period={period} />
      <RowGroup>
        <Row to="/health/heart" icon={<HealthIcon size={20} />} title="Heart adaptation" sub="Heart rate at your easy pace, run by run" />
      </RowGroup>
      <Disclosure id="fitness-details" title="Race predictions, threshold & training status" sub="Garmin’s estimates and what they mean">
        <RaceCard f={f} />
        <ThresholdCard f={f} />
        <TrainingStatusCard period={chosen} />
      </Disclosure>
      {!hasAnything && (
        <Empty title="No fitness data yet">Garmin adds VO2max, race predictions and your threshold after a few runs with heart rate. Sync and check back.</Empty>
      )}
    </div>
  )
}

function Vo2Card({ vo2, period }: { vo2: NonNullable<HealthFitness['vo2max']>; period: Period }) {
  const points = bucket(vo2.series.map((p) => ({ date: p.date, value: p.value })), period.freq, 'last')
  const first = vo2.series[0]
  return (
    <section className="card">
      <div className="kit-head" style={{ alignItems: 'flex-start' }}>
        <div className="grow">
          <span className="title-info"><span className="lbl">VO2max</span><InfoButton k="vo2max" normal={first ? `${one(first.value)} at the start of this period` : undefined} /></span>
          <div className="big-num">{one(vo2.current!)}</div>
        </div>
        <Delta value={vo2.change} better="higher" format={one} suffix={inWords(period)} />
      </div>
      {points.length >= 2 ? (
        <ChartFrame caption={<>{first ? `From ${one(first.value)} on ${dayMonth(first.date)} to ${one(vo2.current!)} now. Higher = more aerobic engine.` : null}<span className="block">{periodCaption(period, { compare: false })}</span></>}>
          <MetricChart data={points} format={one} height={170} step average={false} freq={period.freq} />
        </ChartFrame>
      ) : (
        <p className="chart-caption">Garmin estimates VO2max from runs with heart rate. A trend appears after a few.</p>
      )}
    </section>
  )
}

function AgeEndurance({ f, period }: { f: HealthFitness | null | undefined; period: Period }) {
  const age = f?.fitness_age
  const end = f?.endurance_score
  const tiles = []
  if (age?.current != null) {
    const diff = age.chronological_age != null ? age.chronological_age - age.current : null
    tiles.push(
      <MetricTile
        key="age"
        label="Fitness age"
        info={<InfoButton k="fitness_age" normal={age.chronological_age != null ? `Your real age is ${age.chronological_age}` : undefined} />}
        value={Math.round(age.current)}
        chip={<Delta value={age.change} better="lower" format={(v) => one(v)} unit="yr" />}
        sub={diff != null ? (
          <>You're {age.chronological_age} · <span className={diff >= 0 ? 'good-text' : 'bad'}>{Math.abs(Math.round(diff))} yrs {diff >= 0 ? 'younger' : 'older'}</span></>
        ) : age.achievable != null ? `Achievable: ${Math.round(age.achievable)}` : undefined}
      >
        {age.series.length >= 2 && <Sparkline values={bucket(age.series, period.freq, 'last').map((p) => -(p.value ?? 0))} height={32} color="var(--run)" />}
      </MetricTile>,
    )
  }
  if (end?.current != null) {
    tiles.push(
      <MetricTile
        key="end"
        label="Endurance"
        info={<InfoButton k="endurance_score" normal={end.level ? `Garmin rates this “${end.level}”` : undefined} />}
        value={end.current.toLocaleString()}
        chip={<Delta value={end.change} better="higher" format={(v) => Math.round(v).toLocaleString()} />}
        sub={end.level ?? inWords(period)}
      >
        {end.series.length >= 2 && <Sparkline values={bucket(end.series, period.freq, 'last').map((p) => p.value ?? 0)} height={32} color="var(--run)" />}
      </MetricTile>,
    )
  }
  if (!tiles.length) return null
  return <div className="mt-grid">{tiles}</div>
}

const RACES: Array<[keyof RacePred, string]> = [['5k_s', '5K'], ['10k_s', '10K'], ['half_s', 'Half'], ['marathon_s', 'Marathon']]

function RaceCard({ f }: { f: HealthFitness | null | undefined }) {
  const rp = f?.race_predictions
  const cur = rp?.current
  if (!cur || !RACES.some(([k]) => cur[k])) return null
  return (
    <section className="card">
      <CardHead title={<span className="title-info">Race predictions<InfoButton k="race_predictions" /></span>} sub={rp?.previous_as_of ? `vs ${dayMonth(rp.previous_as_of)}` : undefined} />
      <div className="rp-grid">
        {RACES.filter(([k]) => cur[k]).map(([k, label]) => {
          const now = cur[k] as number
          const before = rp?.previous?.[k] ?? null
          const diff = before != null ? now - before : null
          const tone = diff == null || Math.abs(diff) < 1 ? 'flat' : diff < 0 ? 'good' : 'bad'
          return (
            <div key={k} className="rp">
              <span className="lbl">{label}</span>
              <div className="rp-value">{duration(now)}</div>
              {diff != null && (
                <div className={`rp-delta is-${tone}`}>
                  {tone === 'flat' ? '— same' : `${diff < 0 ? '▼' : '▲'} ${duration(Math.abs(diff))} ${diff < 0 ? 'faster' : 'slower'}`}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

const ZONE_BG = ['var(--run-soft)', 'var(--easy-2)', 'var(--run)', '#f26b3a', '#c93d17']

export function ZoneStrip({ zones }: { zones: AthleteZones }) {
  const list = zones.zones ?? []
  if (!list.length) return null
  return (
    <>
      <div className="zone-strip" role="img" aria-label={list.map((z) => `${z.name} ${z.low}–${z.high} bpm`).join(', ')}>
        {list.map((z, i) => (
          <span key={z.name} style={{ flexGrow: Math.max(1, z.high - z.low), flexBasis: 0, background: ZONE_BG[i] ?? 'var(--run)', color: i === 0 ? 'var(--run-ink)' : '#fff' }}>
            {z.name.replace(/^zone\s*/i, 'Z')}
          </span>
        ))}
      </div>
      <div className="zone-ticks">
        {list.map((z) => <span key={z.name}>{z.low}</span>)}
        <span>{list[list.length - 1].high}</span>
      </div>
    </>
  )
}

function ThresholdCard({ f }: { f: HealthFitness | null | undefined }) {
  const lt = f?.lactate_threshold
  const zones = f?.zones
  if (!lt && !zones?.zones?.length) return null
  const z2 = zones?.zones?.[1]
  return (
    <section className="card">
      <CardHead
        title={lt ? <span className="title-info">Lactate threshold<InfoButton k="lactate_threshold" /></span> : 'Heart-rate zones'}
        aside={lt?.zones_updated ? <Pill topic="run">Zones updated</Pill> : undefined}
        sub={lt?.date ? `Garmin, ${dayMonth(lt.date)}` : zones?.source === 'heart_rate_reserve' ? 'From your resting and max HR' : zones?.source === 'percent_of_max' ? 'Same as your Garmin watch (% of max HR)' : undefined}
      />
      {lt && (
        <div className="stat-pair">
          {lt.hr != null && <div><b>{lt.hr} bpm</b><span className="lbl">threshold HR</span></div>}
          {lt.pace_s_per_km != null && <div><b>{pace(lt.pace_s_per_km)} /km</b><span className="lbl">threshold pace</span></div>}
        </div>
      )}
      {zones && <ZoneStrip zones={zones} />}
      {z2 && <p className="chart-caption" style={{ marginTop: 8 }}>Your easy runs target {z2.low}–{z2.high} bpm.{zones?.capped ? ' Easy zones were kept no harder than before, for safety.' : ''}</p>}
    </section>
  )
}
