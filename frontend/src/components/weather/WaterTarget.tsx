import { todayISO } from '../../lib/format'
import { useWeatherToday } from '../../lib/queries'
import type { DietDay } from '../../lib/types'
import { DropIcon } from '../Icons'
import { WaterLog } from '../today/WaterLog'
import { deg } from './weatherUtil'

/** Diet: water log (R11) or target, with the hot-weather bonus called out, plus the forecast's food tip. */
export function WaterTarget({ day }: { day: DietDay }) {
  const isToday = day.date === todayISO()
  const weather = useWeatherToday()
  const w = isToday ? weather.data : null
  const bonus = day.targets.water_bonus_ml ?? w?.daily_water_bonus_ml ?? 0
  const food = day.weather_tips?.length ? day.weather_tips : w?.food ?? []
  return (
    <>
      {day.water ? (
        <WaterLog date={day.date} fallback={day.water} />
      ) : (
        <span className="water">
          <DropIcon size={16} /> {(day.targets.water_ml / 1000).toFixed(1)} L water
          {bonus > 0 && <span className="tag tag-warn tag-plain water-bonus">+{(bonus / 1000).toFixed(bonus % 500 ? 2 : 1)} L for heat</span>}
        </span>
      )}
      {day.targets.water_note && <p className="muted small">{day.targets.water_note}</p>}
      {bonus > 0 && food.length > 0 && (
        <div className="hot-tip">
          <p className="hot-tip-title">{bonus >= 500 ? 'Hot day' : 'Warm day'}{w?.now?.feels_like != null ? ` · feels like ${deg(w.now.feels_like)} now` : ''}</p>
          <ul>{food.map((f, i) => <li key={i}>{f}</li>)}</ul>
        </div>
      )}
    </>
  )
}
