import { timeOfDay } from '../lib/format'
import type { Meal } from '../lib/types'
import { DietIcon, SparkIcon } from './Icons'

/** Meal row: thumbnail, description, kcal + macros, AI tag. Used in Diet and as a chat attachment. */
export function MealSummary({ meal, showTime = true }: { meal: Meal; showTime?: boolean }) {
  return (
    <div className="meal">
      <div className="meal-thumb">
        {meal.photo_url ? <img src={meal.photo_url} alt="" loading="lazy" /> : <DietIcon size={22} />}
      </div>
      <div className="meal-main">
        <p className="meal-desc">{meal.description || meal.items.map((i) => i.name).join(', ')}</p>
        <p className="meal-macros">
          {showTime && <span>{timeOfDay(meal.eaten_at)} · </span>}
          C {Math.round(meal.carbs_g)} · P {Math.round(meal.protein_g)} · F {Math.round(meal.fat_g)} g
        </p>
        {meal.source !== 'manual' && (
          <span className="tag tag-ai">
            <SparkIcon size={12} /> AI estimate
          </span>
        )}
      </div>
      <div className="meal-kcal">
        <strong>{Math.round(meal.kcal)}</strong>
        <span>kcal</span>
      </div>
    </div>
  )
}
