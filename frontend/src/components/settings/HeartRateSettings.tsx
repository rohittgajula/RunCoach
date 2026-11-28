import { Field } from '../Field'
import { InfoButton } from '../health/InfoButton'
import { Toggle } from './HabitSettings'
import type { Draft, SetDraft } from './settingsDraft'

/** Garmin's running zones: 50/60/70/80/90 % of max, each zone ends one below the next. */
export function percentOfMaxZones(maxHr: number): Array<{ name: string; low: number; high: number }> {
  const floors = [0.5, 0.6, 0.7, 0.8, 0.9].map((f) => Math.floor(maxHr * f + 0.5))
  return floors.map((low, i) => ({ name: `Zone ${i + 1}`, low, high: i < 4 ? floors[i + 1] - 1 : maxHr }))
}

/**
 * Heart rate: which zones the app uses, and the athlete's own easy-run range.
 * Plain language on purpose — the confusion this fixes was two different "zone 2"s.
 */
export function HeartRateSettings({ draft, set, errors }: { draft: Draft; set: SetDraft; errors: Record<string, string> }) {
  const maxHr = Number(draft.max_hr)
  const preview = draft.zones_source === 'percent_of_max' && maxHr >= 120 ? percentOfMaxZones(maxHr) : null
  return (
    <div className="stack">
      <Field label="Heart-rate zones" error={errors.zones_source}>
        <select value={draft.zones_source} onChange={(e) => set('zones_source', e.target.value as Draft['zones_source'])}>
          <option value="percent_of_max">Same as my Garmin watch</option>
          <option value="heart_rate_reserve">Resting + max HR</option>
          {draft.zones_source === 'lactate_threshold' && <option value="lactate_threshold">Garmin lactate threshold</option>}
        </select>
      </Field>
      <p className="muted small">
        {draft.zones_source === 'percent_of_max'
          ? 'Zones are a percentage of your max HR — exactly how your Garmin watch works, so the app and the watch show the same zone numbers. Set Max HR (in "You") to the max your watch uses.'
          : draft.zones_source === 'heart_rate_reserve'
            ? 'Zones also use your resting HR, which gives higher numbers than your watch shows. Your watch\'s "zone 3" can be the app\'s "zone 2" — pick "Same as my Garmin watch" to avoid that.'
            : 'Zones come from the lactate threshold your watch measured.'}
      </p>
      {preview && (
        <ul className="small muted">
          {preview.map((z) => <li key={z.name}>{z.name}: {z.low}–{z.high} bpm</li>)}
        </ul>
      )}

      <Toggle
        label="Use my own easy-run range"
        hint="Every easy, long and run/walk session targets this range in the running parts, instead of zone 2. Your watch gets the same numbers."
        on={draft.hr_easy_custom}
        onChange={(v) => set('hr_easy_custom', v)}
      />
      {draft.hr_easy_custom && (
        <>
          <div className="grid-2">
            <Field label="Easy from (bpm)" error={errors.hr_easy_min}>
              <input inputMode="numeric" value={draft.hr_easy_min} onChange={(e) => set('hr_easy_min', e.target.value)} />
            </Field>
            <Field label="Easy up to (bpm)" error={errors.hr_easy_max}>
              <input inputMode="numeric" value={draft.hr_easy_max} onChange={(e) => set('hr_easy_max', e.target.value)} />
            </Field>
            <Field label="Walk above (bpm)" error={errors.hr_ceiling}>
              <input inputMode="numeric" value={draft.hr_ceiling} onChange={(e) => set('hr_ceiling', e.target.value)} />
            </Field>
          </div>
          <div className="muted small">
            How to run it: stay inside the easy range while running. A few beats over the top — slow to a shuffle.
            Over "walk above" — walk until your HR drops about 20 beats, then jog again. You should be able to talk in full sentences.
            <InfoButton title="Why this range?">
              <p>Easy running builds your aerobic base: more blood vessels and mitochondria in your legs, a stronger heart, and in a few weeks a faster pace at the same heart rate.</p>
              <p>At the start, even a slow jog pushes heart rate up fast, so a beginner's easy range often sits at the top of zone 2 and into zone 3. That's fine — the walk breaks pull it back down.</p>
              <p>If your HR keeps climbing during a run at the same pace, the run is too hard for today: slow down or walk more.</p>
            </InfoButton>
          </div>
        </>
      )}
    </div>
  )
}
