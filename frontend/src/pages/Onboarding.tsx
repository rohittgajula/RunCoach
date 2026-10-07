import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Field } from '../components/Field'
import { GarminConnect } from '../components/GarminConnect'
import { useAuth } from '../lib/AuthContext'
import { errorText } from '../lib/queries'
import { BUILD_PLAN_PROMPT } from '../lib/prompts'

/**
 * Two steps, then straight into a conversation. The coach asks for everything else
 * (race date, days per week, injuries) in chat — a long form here would ask for
 * numbers the athlete doesn't know yet and the Garmin history already holds.
 */
export default function Onboarding() {
  const { athlete, updateAthlete } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState<'name' | 'garmin'>('name')
  const [name, setName] = useState(athlete?.display_name ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function finish() {
    setBusy(true)
    setError(null)
    try {
      await updateAthlete({ onboarding_complete: true })
      navigate('/chat/new', { replace: true, state: { prompt: BUILD_PLAN_PROMPT } })
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }

  return (
    <div className="page auth-page">
      <div className="logo auth-logo">Run<span className="logo-accent">Coach</span></div>
      <p className="eyebrow">Step {step === 'name' ? 1 : 2} of 2</p>

      {step === 'name' ? (
        <form
          className="card stack"
          onSubmit={async (e) => {
            e.preventDefault()
            try {
              await updateAthlete({ display_name: name.trim() })
              setStep('garmin')
            } catch (err) {
              setError(errorText(err))
            }
          }}
        >
          <h1 className="card-title-lg">What should your coach call you?</h1>
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
          </Field>
          {error && <p className="field-error">{error}</p>}
          <button className="btn btn-primary btn-block">Continue</button>
        </form>
      ) : (
        <div className="card stack">
          <h1 className="card-title-lg">Connect Garmin</h1>
          <p className="muted">
            Your history is what the plan is built from — the coach reads every run, split into
            what you actually ran and what you walked.
          </p>
          <GarminConnect compact onConnected={finish} />
          {error && <p className="field-error">{error}</p>}
          <button type="button" className="btn btn-ghost btn-block" onClick={finish} disabled={busy}>
            {busy ? 'Starting…' : 'Skip for now'}
          </button>
        </div>
      )}
    </div>
  )
}
