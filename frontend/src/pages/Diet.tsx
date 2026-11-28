import { useState } from 'react'
import { FuelRows } from '../components/DetailSheets'
import { ChevronLeft, ChevronRight, DietIcon, GearIcon, MoreVIcon, PlusIcon, RunIcon } from '../components/Icons'
import { KcalRing } from '../components/KcalRing'
import { LogMealSheet, MEAL_TYPES } from '../components/LogMealSheet'
import { MacroBar } from '../components/MacroBar'
import { MealSummary } from '../components/MealCard'
import { BodyCard } from '../components/BodyCard'
import { BalanceCard } from '../components/diet/BalanceCard'
import { PreMealCheck } from '../components/diet/PreMealCheck'
import { DayPlan } from '../components/diet/DayPlan'
import { MissingCard } from '../components/diet/MissingCard'
import { FoodPreferences } from '../components/diet/FoodPreferences'
import { PageHeader } from '../components/PageHeader'
import { SeeDetails } from '../components/Disclose'
import { useShell } from '../components/Shell'
import { WaterTarget } from '../components/weather/WaterTarget'
import { Empty, ErrorState, Skeleton } from '../components/States'
import { addDays, parseDate, todayISO } from '../lib/format'
import { errorText, useDeleteMeal, useDietDay } from '../lib/queries'
import type { DietDay, Meal } from '../lib/types'

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
  /**
   * Three questions, three views, rather than one scroll that answers all of
   * them at once: what should I eat, what have I eaten, and what keeps going
   * wrong. They are read at different moments and only one of them is ever the
   * reason the tab was opened.
   */
  const [view, setView] = useState<'eat' | 'log' | 'patterns' | 'prefs'>('eat')
  const day = useDietDay(date)
  const [logOpen, setLogOpen] = useState(false)
  const [editing, setEditing] = useState<Meal | null>(null)
  // The pre-meal verdict carries its own log button; the FAB would cover it.
  const [checking, setChecking] = useState(false)
  const maxDate = addDays(todayISO(), 7)
  const data = day.data?.date === date ? day.data : undefined

  return (
    <div className="page">
      <PageHeader
        title="Food"
        right={
          <button
            type="button" className="icon-btn" aria-label="Food preferences"
            aria-pressed={view === 'prefs'}
            onClick={() => setView((v) => (v === 'prefs' ? 'eat' : 'prefs'))}
          >
            <GearIcon size={20} />
          </button>
        }
      />

      {view !== 'prefs' && (
        <nav className="segmented segmented-full" aria-label="Food views">
          {([['eat', 'Eat'], ['log', 'Logged'], ['patterns', 'Patterns']] as const).map(([key, label]) => (
            <button
              key={key} type="button"
              className={`segmented-option${view === key ? ' is-active' : ''}`}
              aria-current={view === key ? 'page' : undefined}
              onClick={() => setView(key)}
            >
              {label}
            </button>
          ))}
        </nav>
      )}

      {view === 'prefs' && <FoodPreferences />}

      {view === 'patterns' && (
        <>
          <MissingCard />
          <BodyCard />
          <BalanceCard />
        </>
      )}

      {view === 'eat' && (
        <>
          {data && <TargetsCard day={data} />}
          <DayPlan />
          <PreMealCheck date={todayISO()} onOpen={setChecking} />
          {data && data.fueling.length > 0 && <FuelCard day={data} />}
        </>
      )}

      {view === 'log' && (
      <>
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
          <MealsCard
            meals={data.meals}
            onAdd={() => setLogOpen(true)}
            onEdit={(meal) => setEditing(meal)}
          />
        </>
      )}

      </>
      )}

      {view === 'log' && !checking && (
        <button type="button" className="fab" onClick={() => setLogOpen(true)} aria-label="Log meal">
          <PlusIcon size={22} /> Log meal
        </button>
      )}

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
        <WaterTarget day={day} />
        <SeeDetails label="How today’s targets work" title="Today’s targets">
          <section className="card stack-sm">
            {targets.rationale && <p className="rationale">{targets.rationale}</p>}
            <p className="muted small">
              Burn: {Math.round(burn.bmr)} BMR · {Math.round(burn.non_exercise)} daily life · {Math.round(burn.exercise)} exercise
              {burn.exercise_source !== 'none' && ` (${burn.exercise_source === 'garmin' ? 'from Garmin' : 'planned'})`}
            </p>
          </section>
        </SeeDetails>
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

