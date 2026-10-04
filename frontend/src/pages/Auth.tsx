import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Field } from '../components/Field'
import { useAuth } from '../lib/AuthContext'
import { ApiError, api, type RegistrationMode } from '../lib/auth'
import { errorText } from '../lib/queries'

function Logo() {
  return (
    <div className="logo auth-logo">
      Run<span className="logo-accent">Coach</span>
    </div>
  )
}

export function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page auth-page">
      <Logo />
      <p className="muted auth-tagline">Your AI running coach — plan, chat, fuel.</p>
      <form className="card stack" onSubmit={submit}>
        <Field label="Username">
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </Field>
        <Field label="Password">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </Field>
        {error && <p className="field-error">{error}</p>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="muted auth-switch">New here? <Link to="/register">Create an account</Link></p>
    </div>
  )
}

function PrivacyNote() {
  return (
    <p className="muted small auth-privacy">
      RunCoach stores your profile, runs synced from Garmin, journal, meals and chats. Coaching
      text is sent to OpenAI to generate replies — API data is not used to train their models.
      Accounts are invite-only, and you can delete yours, with everything in it, from Settings
      at any time.
    </p>
  )
}

export function Register() {
  const { register } = useAuth()
  const [form, setForm] = useState({ display_name: '', username: '', email: '', password: '', invite_code: '' })
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<RegistrationMode | null>(null)

  useEffect(() => {
    let cancelled = false
    api<{ mode: RegistrationMode }>('/auth/registration/')
      .then((r) => !cancelled && setMode(r.mode))
      // Unknown: show the field anyway; the server decides.
      .catch(() => !cancelled && setMode('invite'))
    return () => {
      cancelled = true
    }
  }, [])
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      const { invite_code, ...rest } = form
      await register({
        ...rest,
        ...(mode === 'invite' ? { invite_code: invite_code.trim() } : {}),
        username: form.username.trim(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      })
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setMode('closed')
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors())
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page auth-page">
      <Logo />
      {mode === 'closed' ? (
        <div className="card stack">
          <p>Registration is closed right now.</p>
          <p className="muted small">RunCoach is invite-only. Ask Rohit for an invite.</p>
        </div>
      ) : (
      <>
      <p className="muted auth-tagline">Create your account. Your timezone is set from this device.</p>
      <form className="card stack" onSubmit={submit}>
        {mode === 'invite' && (
          <Field label="Invite code" hint="RunCoach is invite-only" error={fieldErrors.invite_code}>
            <input
              value={form.invite_code}
              onChange={set('invite_code')}
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              required
            />
          </Field>
        )}
        <Field label="Your name">
          <input value={form.display_name} onChange={set('display_name')} autoComplete="name" required />
        </Field>
        <Field label="Username">
          <input value={form.username} onChange={set('username')} autoComplete="username" required />
        </Field>
        <Field label="Email" hint="Optional">
          <input type="email" value={form.email} onChange={set('email')} autoComplete="email" />
        </Field>
        <Field label="Password" hint="At least 8 characters">
          <input type="password" value={form.password} onChange={set('password')} autoComplete="new-password" minLength={8} required />
        </Field>
        {error && <p className="field-error">{error}</p>}
        <button className="btn btn-primary btn-block" disabled={busy || mode === null}>{busy ? 'Creating…' : 'Create account'}</button>
        <PrivacyNote />
      </form>
      </>
      )}
      <p className="muted auth-switch">Already have one? <Link to="/login">Sign in</Link></p>
    </div>
  )
}
