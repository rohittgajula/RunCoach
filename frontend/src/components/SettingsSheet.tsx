import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'
import { ApiError, api, type Athlete } from '../lib/auth'
import { errorText, invalidatePlanData, useActivePlan } from '../lib/queries'
import { installState, promptInstall, type InstallState } from '../lib/install'
import { getThemePref, setThemePref, type ThemePref } from '../lib/theme'
import { BottomSheet } from './BottomSheet'
import { DayPicker } from './DayPicker'
import { Field } from './Field'
import { GarminConnect } from './GarminConnect'

type Draft = {
  display_name: string
  sex: '' | 'male' | 'female'
  date_of_birth: string
  height_cm: string
  timezone: string
  available_days: Record<string, boolean>
  long_run_day: number
  max_hr: string
  resting_hr: string
  diet_goal: 'maintain' | 'lose' | 'gain'
  diet_rate_kg_per_week: number
}

const toDraft = (a: Athlete): Draft => ({
  display_name: a.display_name ?? '',
  sex: a.sex ?? '',
  date_of_birth: a.date_of_birth ?? '',
  height_cm: a.height_cm != null ? String(a.height_cm) : '',
  timezone: a.timezone ?? '',
  available_days: a.available_days ?? {},
  long_run_day: a.long_run_day ?? 6,
  max_hr: a.max_hr != null ? String(a.max_hr) : '',
  resting_hr: a.resting_hr != null ? String(a.resting_hr) : '',
  diet_goal: a.diet_goal ?? 'maintain',
  diet_rate_kg_per_week: a.diet_rate_kg_per_week ?? 0.25,
})

const num = (text: string) => (text.trim() === '' ? null : Number(text))

function DeleteAccount({ onDeleted }: { onDeleted: () => void }) {
  const { deleteAccount } = useAuth()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!open) {
    return (
      <>
        <p className="muted small">
          Removes your account and everything in it — runs, plans, journal, meals and photos,
          chats, and your Garmin connection. This cannot be undone.
        </p>
        <button type="button" className="btn btn-danger btn-sm" onClick={() => setOpen(true)}>
          Delete account…
        </button>
      </>
    )
  }

  async function confirm() {
    setBusy(true)
    setError('')
    try {
      await deleteAccount(password)
      onDeleted()
    } catch (caught) {
      setError(errorText(caught, 'Could not delete the account.'))
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <Field label="Type DELETE to confirm">
        <input value={typed} onChange={(e) => setTyped(e.target.value)} autoCapitalize="characters" autoComplete="off" />
      </Field>
      <Field label="Your password">
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      </Field>
      {error && <p className="field-error">{error}</p>}
      <div className="row-end">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-danger btn-sm"
          onClick={confirm}
          disabled={busy || typed !== 'DELETE' || !password}
        >
          {busy ? 'Deleting…' : 'Delete my account'}
        </button>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card settings-section">
      <h3 className="card-title">{title}</h3>
      {children}
    </section>
  )
}

export function SettingsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { athlete, username, updateAthlete, logout } = useAuth()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [draft, setDraft] = useState<Draft | null>(athlete ? toDraft(athlete) : null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [theme, setTheme] = useState<ThemePref>(getThemePref())
  // Plans are stored, so new training days change nothing until the plan is rebuilt.
  // Saving them used to look like a broken Save; now we offer the rebuild explicitly.
  const activePlan = useActivePlan()
  const [offerRebuild, setOfferRebuild] = useState(false)
  const [rebuild, setRebuild] = useState<{ busy: boolean; done: boolean; error: string }>({ busy: false, done: false, error: '' })
  const [install, setInstall] = useState<InstallState>({ kind: 'unsupported' })

  // Reset the form when the sheet OPENS — not whenever `athlete` changes. Saving
  // updates `athlete`, and re-running this then wiped the just-shown rebuild offer.
  const wasOpen = useRef(false)
  useEffect(() => {
    if (open && !wasOpen.current && athlete) {
      setDraft(toDraft(athlete))
      setErrors({})
      setSaved(false)
      setOfferRebuild(false)
      setRebuild({ busy: false, done: false, error: '' })
      setInstall(installState())
    }
    wasOpen.current = open
  }, [open, athlete])

  if (!draft) return null

  const dirty = !!athlete && JSON.stringify(draft) !== JSON.stringify(toDraft(athlete))

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft({ ...draft, [key]: value })
    setSaved(false)
  }

  async function save() {
    if (!draft) return
    setBusy(true)
    setErrors({})
    try {
      await updateAthlete({
        display_name: draft.display_name,
        sex: draft.sex || null,
        date_of_birth: draft.date_of_birth || null,
        height_cm: num(draft.height_cm),
        timezone: draft.timezone,
        available_days: draft.available_days,
        long_run_day: draft.long_run_day,
        max_hr: num(draft.max_hr),
        resting_hr: num(draft.resting_hr),
        diet_goal: draft.diet_goal,
        diet_rate_kg_per_week: draft.diet_rate_kg_per_week,
      })
      const daysChanged =
        !!athlete &&
        (JSON.stringify(athlete.available_days ?? {}) !== JSON.stringify(draft.available_days) ||
          athlete.long_run_day !== draft.long_run_day)
      setSaved(true)
      if (daysChanged && activePlan.data) setOfferRebuild(true)
      // Targets, plan and profile all read these fields.
      for (const key of ['diet-day', 'profile-summary', 'calendar']) client.invalidateQueries({ queryKey: [key] })
    } catch (caught) {
      setErrors(caught instanceof ApiError ? caught.fieldErrors() : { detail: 'Could not save.' })
    } finally {
      setBusy(false)
    }
  }

  async function rebuildPlan() {
    setRebuild({ busy: true, done: false, error: '' })
    try {
      await api('/plans/active/rebuild/', { method: 'POST' })
      invalidatePlanData(client)
      setRebuild({ busy: false, done: true, error: '' })
      setOfferRebuild(false)
    } catch (caught) {
      setRebuild({ busy: false, done: false, error: errorText(caught, 'Could not rebuild the plan.') })
    }
  }

  const chooseTheme = (pref: ThemePref) => {
    setTheme(pref)
    setThemePref(pref)
  }

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      title="Settings"
      full
      footer={
        dirty || offerRebuild || rebuild.done ? (
          <div className="settings-footer">
            {offerRebuild ? (
              <>
                <p className="small">
                  Saved. Your plan still uses your old days — rebuild it for the new ones? Completed
                  runs are kept.
                </p>
                {rebuild.error && <p className="bad small">{rebuild.error}</p>}
                <div className="row-end">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOfferRebuild(false)}>
                    Not now
                  </button>
                  <button type="button" className="btn btn-primary btn-sm" onClick={rebuildPlan} disabled={rebuild.busy}>
                    {rebuild.busy ? 'Rebuilding…' : 'Rebuild plan'}
                  </button>
                </div>
              </>
            ) : rebuild.done && !dirty ? (
              <p className="small">Plan rebuilt for your new days — check the Calendar.</p>
            ) : (
              <div className="settings-dirty">
                <span className="small">Unsaved changes</span>
                <button type="button" className="btn btn-primary btn-sm" onClick={save} disabled={busy}>
                  {busy ? 'Saving…' : 'Save'}
                </button>
              </div>
            )}
          </div>
        ) : undefined
      }
    >
      <div className="stack-lg">
        <Section title="Garmin">
          <GarminConnect />
        </Section>

        <Section title="You">
          <Field label="Name" error={errors.display_name}>
            <input value={draft.display_name} onChange={(e) => set('display_name', e.target.value)} />
          </Field>
          <div className="grid-2">
            <Field label="Sex" hint="For calorie targets" error={errors.sex}>
              <select value={draft.sex} onChange={(e) => set('sex', e.target.value as Draft['sex'])}>
                <option value="">Prefer not to say</option>
                <option value="female">Female</option>
                <option value="male">Male</option>
              </select>
            </Field>
            <Field label="Birth date" error={errors.date_of_birth}>
              <input type="date" value={draft.date_of_birth} onChange={(e) => set('date_of_birth', e.target.value)} />
            </Field>
            <Field label="Height (cm)" error={errors.height_cm}>
              <input inputMode="decimal" value={draft.height_cm} onChange={(e) => set('height_cm', e.target.value)} />
            </Field>
            <Field label="Timezone" error={errors.timezone}>
              <input value={draft.timezone} onChange={(e) => set('timezone', e.target.value)} />
            </Field>
            <Field label="Max HR" error={errors.max_hr}>
              <input inputMode="numeric" value={draft.max_hr} onChange={(e) => set('max_hr', e.target.value)} />
            </Field>
            <Field label="Resting HR" error={errors.resting_hr}>
              <input inputMode="numeric" value={draft.resting_hr} onChange={(e) => set('resting_hr', e.target.value)} />
            </Field>
          </div>
          <p className="muted small">Weight and threshold pace live in Profile, with their history.</p>
        </Section>

        <Section title="Training days">
          <DayPicker
            value={draft.available_days}
            onChange={(next) => set('available_days', next)}
            longRunDay={draft.long_run_day}
            onLongRunDayChange={(day) => set('long_run_day', day)}
          />
          <p className="muted small">
            Tick every day you <em>could</em> run. The plan picks up to 4 run days (5 once your
            volume grows), spreads them out with rest between, and makes the others optional walks.
          </p>
          {errors.available_days && <p className="field-error">{errors.available_days}</p>}
          {errors.long_run_day && <p className="field-error">{errors.long_run_day}</p>}
        </Section>

        <Section title="Diet goal">
          <div className="segmented segmented-full" role="radiogroup" aria-label="Diet goal">
            {(['lose', 'maintain', 'gain'] as const).map((goal) => (
              <button
                key={goal}
                type="button"
                role="radio"
                aria-checked={draft.diet_goal === goal}
                className={`segmented-option ${draft.diet_goal === goal ? 'is-active' : ''}`}
                onClick={() => set('diet_goal', goal)}
              >
                {goal[0].toUpperCase() + goal.slice(1)}
              </button>
            ))}
          </div>
          {draft.diet_goal !== 'maintain' && (
            <Field
              label={`Rate: ${draft.diet_rate_kg_per_week.toFixed(2)} kg / week`}
              hint="Never a deficit on long or hard days — the coach removes it automatically."
              error={errors.diet_rate_kg_per_week}
            >
              <input
                type="range"
                min={0}
                max={0.75}
                step={0.05}
                value={draft.diet_rate_kg_per_week}
                onChange={(e) => set('diet_rate_kg_per_week', Number(e.target.value))}
              />
            </Field>
          )}
        </Section>

        {errors.detail && <p className="bad">{errors.detail}</p>}
        <button type="button" className="btn btn-primary btn-block" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : saved ? 'Saved' : 'Save profile'}
        </button>

        <Section title="Appearance">
          <div className="segmented segmented-full" role="radiogroup" aria-label="Theme">
            {(['system', 'light', 'dark'] as const).map((pref) => (
              <button
                key={pref}
                type="button"
                role="radio"
                aria-checked={theme === pref}
                className={`segmented-option ${theme === pref ? 'is-active' : ''}`}
                onClick={() => chooseTheme(pref)}
              >
                {pref[0].toUpperCase() + pref.slice(1)}
              </button>
            ))}
          </div>
        </Section>

        <Section title="App">
          {install.kind === 'installed' && <p className="muted small">Installed on this device.</p>}
          {install.kind === 'prompt-ready' && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={async () => {
                await promptInstall()
                setInstall(installState())
              }}
            >
              Install RunCoach
            </button>
          )}
          {install.kind === 'ios-safari' && (
            <p className="muted small">To install: tap Share, then “Add to Home Screen”.</p>
          )}
          {install.kind === 'ios-other-browser' && (
            <p className="muted small">On iPhone, open RunCoach in Safari to add it to your Home Screen.</p>
          )}
          {install.kind === 'unsupported' && (
            <p className="muted small">Use your browser menu to install this app, if it offers it.</p>
          )}
          <div className="settings-account">
            <span className="muted small">Signed in as {username}</span>
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={async () => {
                await logout()
                client.clear()
                onClose()
                navigate('/login', { replace: true })
              }}
            >
              Log out
            </button>
          </div>
        </Section>

        <Section title="Delete account">
          <DeleteAccount
            onDeleted={() => {
              client.clear()
              onClose()
              navigate('/login', { replace: true })
            }}
          />
        </Section>
      </div>
    </BottomSheet>
  )
}
