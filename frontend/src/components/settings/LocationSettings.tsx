import type { Athlete } from '../../lib/auth'
import { Field } from '../Field'
import { Segmented } from './Segmented'
import type { Draft, SetDraft } from './settingsDraft'

/** Weather location: from the start of your latest run, or a city you type. */
export function LocationSettings({
  draft, set, athlete, errors,
}: { draft: Draft; set: SetDraft; athlete: Athlete; errors: Record<string, string> }) {
  const current = athlete.location_name
  const source = athlete.location_source ?? 'none'
  return (
    <div className="stack">
      <p className="small">
        {current ? (
          <>Now: <b>{current}</b> <span className="muted">({source === 'city' ? 'city you set' : 'from your runs'})</span></>
        ) : (
          <span className="muted">No location yet — it’s taken from your next synced run with GPS, or set a city.</span>
        )}
      </p>
      <Segmented
        label="Location source"
        value={draft.location_source}
        onChange={(v) => set('location_source', v)}
        options={[
          { value: 'runs', label: 'From my runs' },
          { value: 'city', label: 'City' },
        ]}
      />
      {draft.location_source === 'city' && (
        <Field label="City" hint="e.g. Hyderabad" error={errors.location_city ?? errors.location_name}>
          <input value={draft.location_city} onChange={(e) => set('location_city', e.target.value)} autoComplete="address-level2" />
        </Field>
      )}
      {errors.location_source && <p className="field-error">{errors.location_source}</p>}
      <p className="muted small">Used for heat, air quality and hydration advice. Stored to about 1 km.</p>
    </div>
  )
}
