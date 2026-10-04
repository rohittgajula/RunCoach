import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, json } from '../lib/auth'
import { useAuth } from '../lib/AuthContext'
import { errorText, useGarminStatus, useSync } from '../lib/queries'
import type { GarminStatus } from '../lib/types'
import { Field } from './Field'

/** Garmin connect / disconnect / sync, against the existing /garmin/* endpoints. */
export function GarminConnect({ onConnected, compact = false }: { onConnected?: () => void; compact?: boolean }) {
  const client = useQueryClient()
  const { athlete } = useAuth()
  const status = useGarminStatus()
  const sync = useSync()
  const [showForm, setShowForm] = useState(compact)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const connect = useMutation({
    mutationFn: () => api<GarminStatus>('/garmin/connect/', { method: 'POST', ...json({ email, password }) }),
    onSuccess: () => {
      // Held only long enough to send.
      setPassword('')
      setEmail('')
      setShowForm(false)
      setError('')
      client.invalidateQueries({ queryKey: ['garmin-status'] })
      onConnected?.()
    },
    onError: (caught) => setError(errorText(caught, 'Could not reach the server.')),
  })

  const disconnect = useMutation({
    mutationFn: () => api('/garmin/disconnect/', { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['garmin-status'] }),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setError('')
    connect.mutate()
  }

  const connected = status.data?.connected

  if (status.isPending) return <p className="muted">Checking Garmin…</p>

  if (connected) {
    return (
      <div className="garmin">
        <p className="garmin-line">
          <span className="dot dot-ok" /> Connected{status.data?.name ? ` as ${status.data.name}` : ''}
        </p>
        <p className="muted small">
          {status.data?.last_sync ? `Last sync ${new Date(status.data.last_sync).toLocaleString()}` : 'Never synced.'}
        </p>
        {sync.data && (
          <p className={sync.data.failed ? 'bad small' : 'muted small'}>
            {sync.data.imported} imported · {sync.data.skipped} already had · {sync.data.failed} failed
          </p>
        )}
        {sync.isError && <p className="bad small">{errorText(sync.error, 'Sync failed.')}</p>}
        <div className="row-end">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
            Disconnect
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => sync.mutate()} disabled={sync.isPending}>
            {sync.isPending ? 'Syncing…' : 'Sync now'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="garmin">
      {athlete?.garmin_connected && status.data?.error && (
        <p className="bad small">Connection stopped working — {status.data.error}</p>
      )}
      {!showForm ? (
        <>
          <p className="muted small">
            Not connected. RunCoach reads your runs and recovery from Garmin to plan around them.
          </p>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowForm(true)}>
            Connect Garmin
          </button>
        </>
      ) : (
        <form onSubmit={submit} className="stack">
          <p className="muted small">
            Your password is used once to get a session token, then discarded. It is never stored.
          </p>
          <Field label="Garmin email">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" required />
          </Field>
          <Field label="Garmin password">
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" required />
          </Field>
          {error && <p className="bad small" role="alert">{error}</p>}
          <div className="row-end">
            {!compact && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setShowForm(false)
                  setPassword('')
                  setError('')
                }}
              >
                Cancel
              </button>
            )}
            <button className="btn btn-primary btn-sm" disabled={connect.isPending}>
              {connect.isPending ? 'Connecting…' : 'Connect'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
