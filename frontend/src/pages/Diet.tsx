import { useMemo, useState } from 'react'
import { Bar, CartesianGrid, Cell, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ChipButton } from '../components/ChipButton'
import { monthTicks, tickDate } from '../components/chartUtil'
import { FuelRows } from '../components/DetailSheets'
import { ChevronLeft, ChevronRight, DietIcon, DropIcon, GearIcon, MoreVIcon, PlusIcon, RunIcon } from '../components/Icons'
import { KcalRing } from '../components/KcalRing'
import { LogMealSheet, MEAL_TYPES } from '../components/LogMealSheet'
import { MacroBar } from '../components/MacroBar'
import { MealSummary } from '../components/MealCard'
import { PageHeader } from '../components/PageHeader'
import { RangeSwitch } from '../components/RangeSwitch'
import { useShell } from '../components/Shell'
import { Empty, ErrorState, Skeleton } from '../components/States'
import { addDays, parseDate, signed, todayISO } from '../lib/format'
import { errorText, useDeleteMeal, useDietDay, useDietTrend } from '../lib/queries'
import type { DietDay, Meal, Range } from '../lib/types'

const PROFILE_LABEL: Record<string, string> = {
  height_cm: 'height',
  sex: 'sex',
  date_of_birth: 'birth date',
  weight_kg: 'weight',
}

function dayLabel(date: string) {
  const today = todayISO()
  if (date === today) return 'Today'
  if (date === addDays(today, -1)) return 'Yesterday'
  if (date === addDays(today, 1)) return 'Tomorrow'
  return parseDate(date).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

export default function Diet() {
  const { openSettings } = useShell()
  const [date, setDate] = useState(todayISO())
  const day = useDietDay(date)
  const [logOpen, setLogOpen] = useState(false)
  const [editing, setEditing] = useState<Meal | null>(null)
  const maxDate = addDays(todayISO(), 7)
  const data = day.data?.date === date ? day.data : undefined

  return (
    <div className="page">
      <PageHeader
        right={
          <ChipButton label="Settings" onClick={openSettings}>
            <GearIcon />
          </ChipButton>
        }
      />

      <div className="date-switch">
        <button type="button" className="icon-btn" aria-label="Previous day" onClick={() => setDate(addDays(date, -1))}>
          <ChevronLeft />
        </button>
        <button type="button" className="date-switch-label" onClick={() => setDate(todayISO())}>
          {dayLabel(date)}
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-label="Next day"
          disabled={date >= maxDate}
          onClick={() => setDate(addDays(date, 1))}
        >
          <ChevronRight />
        </button>
      </div>

      {day.isError && !data && (
        <ErrorState message={errorText(day.error, 'Your diet day did not load.')} onRetry={() => day.refetch()} />
      )}

      {!data && !day.isError && (
        <>
          <section className="card"><Skeleton height={160} /></section>
          <section className="card"><Skeleton lines={3} /></section>
        </>
      )}

      {data && (
        <>
          {data.missing_profile.length > 0 && (
            <button type="button" className="card notice-card" onClick={openSettings}>
              <span>
                Add your {data.missing_profile.map((f) => PROFILE_LABEL[f] ?? f.replace(/_/g, ' ')).join(', ')} in Settings
                for accurate targets.
              </span>
              <ChevronRight size={18} />
            </button>
          )}
          <TargetsCard day={data} />
          {data.fueling.length > 0 && <FuelCard day={data} />}
          <MealsCard
            meals={data.meals}
            onAdd={() => setLogOpen(true)}
            onEdit={(meal) => setEditing(meal)}
          />
        </>
      )}

      <BalanceCard />

      <button type="button" className="fab" onClick={() => setLogOpen(true)} aria-label="Log meal">
        <PlusIcon size={22} /> Log meal
      </button>

      <LogMealSheet open={logOpen} onClose={() => setLogOpen(false)} date={date} />
      <LogMealSheet open={!!editing} onClose={() => setEditing(null)} meal={editing} date={date} />
    </div>
  )
}

function TargetsCard({ day }: { day: DietDay }) {
  const { targets, eaten, burn } = day
  return (
    <section className="card">
      <div className="targets">
        <KcalRing eaten={eaten.kcal} target={targets.kcal} />
        <div className="targets-macros">
          <MacroBar label="Carbs" tone="carbs" eaten={eaten.carbs_g} target={targets.carbs_g} />
          <MacroBar label="Protein" tone="protein" eaten={eaten.protein_g} target={targets.protein_g} />
          <MacroBar label="Fat" tone="fat" eaten={eaten.fat_g} target={targets.fat_g} />
        </div>
      </div>
      <div className="targets-foot">
        <span className="water">
          <DropIcon size={16} /> {(targets.water_ml / 1000).toFixed(1)} L water
        </span>
        {targets.rationale && <p className="rationale">{targets.rationale}</p>}
        <p className="muted small">
          Burn: {Math.round(burn.bmr)} BMR · {Math.round(burn.non_exercise)} daily life · {Math.round(burn.exercise)} exercise
          {burn.exercise_source !== 'none' && ` (${burn.exercise_source === 'garmin' ? 'from Garmin' : 'planned'})`}
        </p>
      </div>
    </section>
  )
}

function FuelCard({ day }: { day: DietDay }) {
  return (
    <section className="card">
      <h2 className="card-title">Fuel your run</h2>
      {day.fueling.map((f) => (
        <div key={f.workout_id} className="fuel-block">
          <p className="fuel-workout">
            <RunIcon size={18} /> {f.title}
            {f.carbs_g_during_per_h != null && <span className="tag">{f.carbs_g_during_per_h} g carbs/h</span>}
          </p>
          <FuelRows before={f.before} during={f.during} after={f.after} />
        </div>
      ))}
    </section>
  )
}

function MealsCard({ meals, onAdd, onEdit }: { meals: Meal[]; onAdd: () => void; onEdit: (meal: Meal) => void }) {
  const remove = useDeleteMeal()
  const [menu, setMenu] = useState<number | null>(null)
  const [confirm, setConfirm] = useState<number | null>(null)

  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Meals</h2>
      </div>
      {meals.length === 0 && (
        <Empty
          icon={<DietIcon size={32} />}
          title="Nothing logged yet"
          action={<button type="button" className="btn btn-secondary btn-sm" onClick={onAdd}><PlusIcon size={16} /> Log your first meal</button>}
        >
          Snap a photo or type what you ate — the coach estimates it, you confirm.
        </Empty>
      )}
      {MEAL_TYPES.map(({ value, label }) => {
        const group = meals.filter((m) => m.meal_type === value)
        if (!group.length) return null
        const kcal = group.reduce((s, m) => s + m.kcal, 0)
        return (
          <div key={value} className="meal-group">
            <p className="meal-group-head">
              <span>{label}</span>
              <span className="muted">{Math.round(kcal)} kcal</span>
            </p>
            {group.map((meal) =>
              confirm === meal.id ? (
                <div key={meal.id} className="confirm-row">
                  <span className="grow">Delete this meal?</span>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(null)}>Cancel</button>
                  <button
                    type="button"
                    className="btn btn-danger btn-sm"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(meal.id, { onSuccess: () => setConfirm(null) })}
                  >
                    Delete
                  </button>
                </div>
              ) : (
                <div key={meal.id} className="meal-row">
                  <button type="button" className="meal-open" onClick={() => onEdit(meal)}>
                    <MealSummary meal={meal} />
                  </button>
                  <div className="menu-wrap">
                    <button type="button" className="icon-btn" aria-label="Meal options" onClick={() => setMenu(menu === meal.id ? null : meal.id)}>
                      <MoreVIcon size={20} />
                    </button>
                    {menu === meal.id && (
                      <div className="menu" role="menu">
                        <button type="button" role="menuitem" onClick={() => { setMenu(null); onEdit(meal) }}>Edit</button>
                        <button type="button" role="menuitem" className="bad" onClick={() => { setMenu(null); setConfirm(meal.id) }}>Delete</button>
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
          </div>
        )
      })}
      {remove.isError && <p className="bad small">{errorText(remove.error, 'Could not delete.')}</p>}
    </section>
  )
}

function BalanceCard() {
  const [range, setRange] = useState<Range>('3m')
  const trend = useDietTrend(range)

  const series = useMemo(
    () =>
      (trend.data?.series ?? []).map((p) => ({
        date: p.date,
        balance: p.intake_kcal != null ? Math.round(p.intake_kcal - p.target_kcal) : null,
        weight: p.weight_kg,
      })),
    [trend.data],
  )
  const s = trend.data?.summary
  const hasIntake = series.some((p) => p.balance != null)
  const hasWeight = series.some((p) => p.weight != null)

  return (
    <section className="card">
      <h2 className="card-title">Balance vs weight</h2>
      <RangeSwitch value={range} onChange={setRange} />
      {trend.isPending && <Skeleton height={200} />}
      {trend.isError && !trend.data && <ErrorState message={errorText(trend.error)} onRetry={() => trend.refetch()} />}
      {trend.data && (
        <>
          {s && s.logged_days_last_7 < 5 ? (
            <p className="muted small">
              Log at least 5 of the last 7 days to see your balance ({s.logged_days_last_7}/7 so far).
            </p>
          ) : s && s.avg_balance_kcal != null ? (
            <p className="balance-summary">
              Avg <strong>{signed(s.avg_balance_kcal)} kcal/day</strong>
              {s.predicted_kg_per_week != null && <> ≈ {signed(s.predicted_kg_per_week, 1)} kg/week predicted</>}
              {s.actual_kg_per_week != null && <>, {signed(s.actual_kg_per_week, 1)} kg/week actual</>}
            </p>
          ) : null}
          {hasIntake || hasWeight ? (
            <div className="chart" style={{ height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={series} margin={{ top: 8, right: 0, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis
                    dataKey="date"
                    ticks={monthTicks(series.map((p) => p.date))}
                    tickFormatter={tickDate}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={24}
                  />
                  <YAxis yAxisId="kcal" axisLine={false} tickLine={false} width={40} tickCount={4} />
                  <YAxis
                    yAxisId="kg"
                    orientation="right"
                    axisLine={false}
                    tickLine={false}
                    width={36}
                    domain={['dataMin - 1', 'dataMax + 1']}
                    tickFormatter={(v: number) => v.toFixed(0)}
                    hide={!hasWeight}
                  />
                  <Tooltip
                    labelFormatter={(label) => tickDate(String(label))}
                    formatter={(value, name) =>
                      name === 'weight'
                        ? [`${Number(value).toFixed(1)} kg`, 'Weight']
                        : [`${signed(Number(value))} kcal`, 'Balance']
                    }
                  />
                  <Bar yAxisId="kcal" dataKey="balance" isAnimationActive={false} radius={[3, 3, 3, 3]}>
                    {series.map((p) => (
                      <Cell key={p.date} fill={(p.balance ?? 0) < 0 ? '#5aa2f0' : '#f0a35a'} />
                    ))}
                  </Bar>
                  <Line
                    yAxisId="kg"
                    dataKey="weight"
                    stroke="#1f7ae0"
                    strokeWidth={2.5}
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty title="No data yet">Logged meals and weigh-ins appear here.</Empty>
          )}
          <p className="legend">
            <span className="legend-swatch legend-under" /> under target
            <span className="legend-swatch legend-over" /> over target
            <span className="legend-line" /> weight
          </p>
        </>
      )}
    </section>
  )
}
