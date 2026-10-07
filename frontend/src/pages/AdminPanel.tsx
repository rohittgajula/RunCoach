import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BottomSheet } from '../components/BottomSheet'
import { TIP, chartTip, num } from '../components/ChartTip'
import { Disclosure, Row, RowGroup } from '../components/Disclose'
import { Field } from '../components/Field'
import { CardHead, Meter, Pill } from '../components/Kit'
import { PageHeader } from '../components/PageHeader'
import { ErrorState, Skeleton } from '../components/States'
import { ApiError, api, json } from '../lib/auth'
import { errorText } from '../lib/queries'
import {
  useAdminInvites, useAdminSystem, useAdminUsers, useAdminWrite, useAiConfig, useAiPrices, useAiProviders, useAiStats,
  type AdminUser, type AiPrice, type AiStats, type AiTier, type Invite,
} from '../lib/r14admin'

type Tab = 'users' | 'ai' | 'system'
const TABS: Array<{ key: Tab; label: string }> = [{ key: 'users', label: 'Users' }, { key: 'ai', label: 'AI' }, { key: 'system', label: 'System' }]

const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'
const day = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' }) : '—')
const usd = (v: number | null | undefined) => (v == null ? '—' : v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`)
const kTok = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : String(v))
const gb = (b: number | null | undefined) => (b == null ? '—' : `${(b / 2 ** 30).toFixed(b >= 10 * 2 ** 30 ? 0 : 1)} GB`)

/**
 * R14 §14 admin panel (staff only; the route redirects everyone else). Users & invites,
 * AI providers/models/prices/usage, and system health. Never shows a key or secret —
 * the API only says whether one is configured.
 */
export default function AdminPanel() {
  const [tab, setTab] = useState<Tab>(() => {
    try { return (sessionStorage.getItem('rc.admin.tab') as Tab) || 'users' } catch { return 'users' }
  })
  useEffect(() => {
    try { sessionStorage.setItem('rc.admin.tab', tab) } catch { /* ignore */ }
  }, [tab])
  return (
    <div className="page admin-page">
      <PageHeader title="Admin" back="/me" avatar={false} />
      <div className="segmented segmented-full" role="tablist" aria-label="Admin sections">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={`segmented-option ${tab === t.key ? 'is-active' : ''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'users' && <UsersTab />}
      {tab === 'ai' && <AiTab />}
      {tab === 'system' && <SystemTab />}
    </div>
  )
}

function Forbidden({ error, what }: { error: unknown; what: string }) {
  if (error instanceof ApiError && error.status === 403) return <ErrorState message="Staff only." />
  return <ErrorState message={errorText(error, `${what} did not load.`)} />
}

// --- users & invites ------------------------------------------------------------------

function UsersTab() {
  const users = useAdminUsers()
  const [open, setOpen] = useState<AdminUser | null>(null)
  if (users.isPending) return <section className="card"><Skeleton lines={5} /></section>
  if (users.isError) return <Forbidden error={users.error} what="Users" />
  const d = users.data
  const current = open ? d.users.find((u) => u.id === open.id) ?? open : null
  return (
    <div className="stack">
      <section className="card">
        <CardHead title={`${d.users.length} users`} sub={`Sign-up: ${d.registration_mode} · default AI budget ${d.default_budget} calls/month`} />
      </section>
      <RowGroup title="Users">
        {d.users.map((u) => (
          <Row
            key={u.id}
            title={<>{u.display_name || u.username}{!u.is_active && <> <Pill topic="bad">Disabled</Pill></>}{u.is_staff && <> <Pill>Staff</Pill></>}</>}
            sub={`${u.garmin_connected ? `Garmin · ${u.garmin_last_sync ? `synced ${when(u.garmin_last_sync)}` : 'never synced'}` : 'No Garmin'} · AI ${usd(u.ai?.cost_month_usd)} this month`}
            onClick={() => setOpen(u)}
          />
        ))}
      </RowGroup>
      <Invites />
      <BottomSheet open={!!current} onClose={() => setOpen(null)} title={current ? current.display_name || current.username : ''}>
        {current && <UserDetail key={current.id} u={current} defaultBudget={d.default_budget} />}
      </BottomSheet>
    </div>
  )
}

function UserDetail({ u, defaultBudget }: { u: AdminUser; defaultBudget: number }) {
  const write = useAdminWrite<AdminUser>()
  const [confirm, setConfirm] = useState(false)
  const [budget, setBudget] = useState(u.ai?.budget_source === 'custom' ? String(u.ai.budget) : '')
  const patch = (body: Record<string, unknown>) => write.mutate({ path: `/admin/users/${u.id}/`, method: 'PATCH', body }, { onSuccess: () => setConfirm(false) })
  return (
    <div className="stack">
      <dl className="admin-dl">
        <div><dt>Username</dt><dd>{u.username}</dd></div>
        {u.email && <div><dt>Email</dt><dd>{u.email}</dd></div>}
        <div><dt>Joined</dt><dd>{day(u.joined)}</dd></div>
        <div><dt>Last active</dt><dd>{when(u.last_active)}</dd></div>
        <div><dt>Garmin</dt><dd>{u.garmin_connected ? `Linked · last sync ${when(u.garmin_last_sync)}` : 'Not linked'}</dd></div>
        <div><dt>Plan</dt><dd>{u.plan ? `${u.plan.name}${u.plan.race_date ? ` · race ${day(u.plan.race_date)}` : ''}` : 'None'}</dd></div>
        <div><dt>AI this month</dt><dd>{u.ai ? `${u.ai.calls_month} calls · ${usd(u.ai.cost_month_usd)} of ${u.ai.budget} calls (${u.ai.budget_source})` : '—'}</dd></div>
      </dl>
      {u.ai && <Meter value={u.ai.calls_month} max={u.ai.budget || 1} topic="run" over={u.ai.calls_month > u.ai.budget} label="AI calls vs budget" />}
      <div className="row-wrap">
        <input inputMode="numeric" aria-label="AI budget (calls per month)" placeholder={`Default (${defaultBudget})`} value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^\d]/g, ''))} style={{ flex: 1, minWidth: 120 }} />
        <button type="button" className="btn btn-secondary btn-sm" disabled={write.isPending} onClick={() => patch({ ai_budget: budget === '' ? null : Number(budget) })}>Save budget</button>
      </div>
      {confirm ? (
        <div className="confirm-row">
          <span className="grow small">{u.is_active ? 'Disable this account? They are signed out everywhere.' : 'Enable this account again?'}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(false)}>Cancel</button>
          <button type="button" className={`btn btn-sm ${u.is_active ? 'btn-danger' : 'btn-primary'}`} disabled={write.isPending} onClick={() => patch({ is_active: !u.is_active })}>
            {u.is_active ? 'Disable' : 'Enable'}
          </button>
        </div>
      ) : (
        <button type="button" className={`btn btn-sm ${u.is_active ? 'btn-secondary' : 'btn-primary'}`} onClick={() => setConfirm(true)}>
          {u.is_active ? 'Disable user…' : 'Enable user…'}
        </button>
      )}
      {write.isError && <p className="bad small">{errorText(write.error, 'Could not save.')}</p>}
    </div>
  )
}

function Invites() {
  const invites = useAdminInvites()
  const write = useAdminWrite<Invite>()
  const [note, setNote] = useState('')
  const [uses, setUses] = useState('1')
  const [days, setDays] = useState('14')
  const [revoking, setRevoking] = useState<number | null>(null)
  const [copied, setCopied] = useState<number | null>(null)
  const list = invites.data ?? []
  const create = () =>
    write.mutate(
      { path: '/admin/invites/', method: 'POST', body: { note: note.trim(), max_uses: Math.min(100, Math.max(1, Number(uses) || 1)), expires_in_days: days ? Number(days) : null } },
      { onSuccess: () => setNote('') },
    )
  const copy = async (i: Invite) => {
    try {
      await navigator.clipboard.writeText(i.code)
      setCopied(i.id)
    } catch { /* clipboard blocked: the code is on screen */ }
  }
  return (
    <section className="card stack-sm">
      <CardHead title="Invites" sub={`${list.filter((i) => i.usable).length} usable`} />
      <div className="grid-2">
        <Field label="Note"><input value={note} maxLength={200} placeholder="Who it's for" onChange={(e) => setNote(e.target.value)} /></Field>
        <Field label="Uses"><input inputMode="numeric" value={uses} onChange={(e) => setUses(e.target.value.replace(/[^\d]/g, ''))} /></Field>
        <Field label="Expires in (days)" hint="Empty = never"><input inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.replace(/[^\d]/g, ''))} /></Field>
      </div>
      <button type="button" className="btn btn-primary btn-sm" disabled={write.isPending} onClick={create}>Create invite</button>
      {invites.isPending && <Skeleton lines={2} />}
      <ul className="admin-list">
        {list.map((i) => (
          <li key={i.id}>
            <span className="grow">
              <b className="mono">{i.code}</b> {i.revoked ? <Pill topic="bad">Revoked</Pill> : i.usable ? <Pill topic="ok">Usable</Pill> : <Pill>Used up</Pill>}
              <span className="muted small block">{[i.note, `${i.uses}/${i.max_uses} used`, i.expires_at ? `expires ${day(i.expires_at)}` : 'no expiry'].filter(Boolean).join(' · ')}</span>
            </span>
            {i.usable && (
              revoking === i.id ? (
                <span className="row-wrap">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRevoking(null)}>Cancel</button>
                  <button type="button" className="btn btn-danger btn-sm" disabled={write.isPending} onClick={() => write.mutate({ path: `/admin/invites/${i.id}/revoke/`, method: 'POST' }, { onSuccess: () => setRevoking(null) })}>Revoke</button>
                </span>
              ) : (
                <span className="row-wrap">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => copy(i)}>{copied === i.id ? 'Copied' : 'Copy'}</button>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRevoking(i.id)}>Revoke…</button>
                </span>
              )
            )}
          </li>
        ))}
      </ul>
      {write.isError && <p className="bad small">{errorText(write.error, 'Could not save.')}</p>}
    </section>
  )
}

// --- AI ---------------------------------------------------------------------------------

function AiTab() {
  return (
    <div className="stack">
      <Usage />
      <Disclosure id="admin-tiers" title="Models per tier" sub="Provider + model for lite · fast · coach · deep">
        <Tiers />
      </Disclosure>
      <Disclosure id="admin-test" title="Test a prompt" sub="Send one prompt to any configured model">
        <TestPrompt />
      </Disclosure>
      <Disclosure id="admin-prices" title="Price table" sub="USD per 1M tokens, per model">
        <Prices />
      </Disclosure>
      <Disclosure id="admin-providers" title="Providers" sub="OpenAI · Google AI Studio (Gemini)">
        <Providers />
      </Disclosure>
    </div>
  )
}

function Providers() {
  const p = useAiProviders()
  if (p.isPending) return <Skeleton lines={3} />
  if (p.isError) return <Forbidden error={p.error} what="Providers" />
  return (
    <>
      {p.data.map((x) => (
        <section key={x.key} className="card stack-sm">
          <div className="kit-head">
            <span className="grow kit-title">{x.label}</span>
            {x.configured ? <Pill topic="ok">Key configured</Pill> : <Pill topic="bad">No key</Pill>}
          </div>
          <p className="muted small">
            {Object.entries(x.features).filter(([, v]) => v).map(([k]) => k.replace('_', ' ')).join(' · ') || 'No features reported'}
          </p>
          <p className="small">{x.models.length ? x.models.join(', ') : 'No models in the price table yet.'}</p>
        </section>
      ))}
    </>
  )
}

function Tiers() {
  const cfg = useAiConfig()
  const providers = useAiProviders()
  const write = useAdminWrite()
  const [draft, setDraft] = useState<Record<string, { provider: string; model: string }>>({})
  if (cfg.isPending || providers.isPending) return <Skeleton lines={4} />
  if (cfg.isError) return <Forbidden error={cfg.error} what="AI config" />
  const configured = (providers.data ?? []).filter((p) => p.configured)
  const modelsOf = (key: string) => (providers.data ?? []).find((p) => p.key === key)?.models ?? []
  const value = (t: AiTier) => draft[t.tier] ?? { provider: t.provider, model: t.model }
  const changed = Object.entries(draft).filter(([tier, v]) => {
    const t = cfg.data.tiers.find((x) => x.tier === tier)
    return t && (t.provider !== v.provider || t.model !== v.model)
  })
  const save = () =>
    write.mutate(
      { path: '/admin/ai/config/', method: 'PUT', body: { tiers: changed.map(([tier, v]) => ({ tier, ...v })) } },
      { onSuccess: () => setDraft({}) },
    )
  return (
    <section className="card stack">
      {cfg.data.tiers.map((t) => {
        const v = value(t)
        return (
          <div key={t.tier} className="stack-sm admin-tier">
            <div className="kit-head">
              <span className="grow"><b>{t.tier}</b> <span className="muted small">{t.source === 'db' ? `set here${t.updated_at ? ` · ${when(t.updated_at)}` : ''}` : 'from env'}</span></span>
              {!t.available && <Pill topic="bad">Unavailable</Pill>}
            </div>
            <div className="grid-2 grid-2-even">
              <select aria-label={`${t.tier} provider`} value={v.provider} onChange={(e) => setDraft({ ...draft, [t.tier]: { provider: e.target.value, model: modelsOf(e.target.value)[0] ?? '' } })}>
                {configured.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
                {!configured.some((p) => p.key === v.provider) && <option value={v.provider}>{v.provider} (no key)</option>}
              </select>
              <select aria-label={`${t.tier} model`} value={v.model} onChange={(e) => setDraft({ ...draft, [t.tier]: { provider: v.provider, model: e.target.value } })}>
                {modelsOf(v.provider).map((m) => <option key={m} value={m}>{m}</option>)}
                {!modelsOf(v.provider).includes(v.model) && <option value={v.model}>{v.model}</option>}
              </select>
            </div>
            {t.source === 'db' && (
              <button type="button" className="link-btn small" disabled={write.isPending} onClick={() => write.mutate({ path: '/admin/ai/config/', method: 'PUT', body: { tiers: [{ tier: t.tier, reset: true }] } })}>
                Reset to env ({t.env_provider} · {t.env_model})
              </button>
            )}
          </div>
        )
      })}
      <p className="muted small">Uses: {Object.entries(cfg.data.operations).map(([op, tier]) => `${op} → ${tier}`).join(' · ')}</p>
      {write.isError && <p className="bad small">{errorText(write.error, 'Could not save.')}</p>}
      <button type="button" className="btn btn-primary btn-sm" disabled={!changed.length || write.isPending} onClick={save}>
        {write.isPending ? 'Saving…' : changed.length ? `Save ${changed.length} change${changed.length === 1 ? '' : 's'}` : 'No changes'}
      </button>
    </section>
  )
}

type TestResult = { ok: boolean; text: string; latency_ms: number; input_tokens: number; output_tokens: number; cost_usd: number; error: string | null }

function TestPrompt() {
  const providers = useAiProviders()
  const configured = (providers.data ?? []).filter((p) => p.configured)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('Say hello in five words.')
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<TestResult | null>(null)
  const [err, setErr] = useState('')
  const p = provider || configured[0]?.key || ''
  const models = configured.find((x) => x.key === p)?.models ?? []
  const m = model && models.includes(model) ? model : models[0] ?? ''
  const run = async () => {
    setBusy(true)
    setErr('')
    setOut(null)
    try {
      setOut(await api<TestResult>('/admin/ai/test/', { method: 'POST', ...json({ provider: p, model: m, prompt }) }))
    } catch (e) {
      setErr(errorText(e, 'Test failed.'))
    } finally {
      setBusy(false)
    }
  }
  if (providers.isPending) return <Skeleton lines={3} />
  return (
    <section className="card stack-sm">
      <div className="grid-2 grid-2-even">
        <select aria-label="Provider" value={p} onChange={(e) => { setProvider(e.target.value); setModel('') }}>
          {configured.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
        </select>
        <select aria-label="Model" value={m} onChange={(e) => setModel(e.target.value)}>
          {models.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
      </div>
      <textarea aria-label="Prompt" rows={3} maxLength={2000} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      <button type="button" className="btn btn-primary btn-sm" disabled={busy || !p || !m || !prompt.trim()} onClick={run}>{busy ? 'Waiting…' : 'Send test'}</button>
      {err && <p className="bad small">{err}</p>}
      {out && (
        <div className="stack-sm">
          {out.ok ? <p className="admin-reply">{out.text}</p> : <p className="bad small">{out.error ?? 'Failed'}</p>}
          <p className="muted small">{out.latency_ms} ms · {out.input_tokens} in / {out.output_tokens} out · {usd(out.cost_usd)}</p>
        </div>
      )}
    </section>
  )
}

function Prices() {
  const prices = useAiPrices()
  const write = useAdminWrite<AiPrice>()
  const [edit, setEdit] = useState<Record<number, { input: string; output: string }>>({})
  const [add, setAdd] = useState({ provider: 'gemini', model: '', input: '', output: '' })
  const [del, setDel] = useState<number | null>(null)
  if (prices.isPending) return <Skeleton lines={4} />
  if (prices.isError) return <Forbidden error={prices.error} what="Prices" />
  return (
    <section className="card stack-sm">
      <ul className="admin-list">
        {prices.data.map((row) => {
          const e = edit[row.id]
          return (
            <li key={row.id}>
              <span className="grow">
                <b>{row.model}</b> <span className="muted small">{row.provider}</span>
                {!e && <span className="small block">in {usd(row.input_per_m_usd)} · out {usd(row.output_per_m_usd)} per 1M</span>}
                {e && (
                  <span className="row-wrap" style={{ marginTop: 6 }}>
                    <input inputMode="decimal" aria-label="Input USD per 1M" value={e.input} onChange={(x) => setEdit({ ...edit, [row.id]: { ...e, input: x.target.value } })} style={{ width: 90 }} />
                    <input inputMode="decimal" aria-label="Output USD per 1M" value={e.output} onChange={(x) => setEdit({ ...edit, [row.id]: { ...e, output: x.target.value } })} style={{ width: 90 }} />
                  </span>
                )}
              </span>
              {e ? (
                <span className="row-wrap">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => { const n = { ...edit }; delete n[row.id]; setEdit(n) }}>Cancel</button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={write.isPending}
                    onClick={() => write.mutate(
                      { path: `/admin/ai/prices/${row.id}/`, method: 'PATCH', body: { input_per_m_usd: Number(e.input), output_per_m_usd: Number(e.output) } },
                      { onSuccess: () => { const n = { ...edit }; delete n[row.id]; setEdit(n) } },
                    )}
                  >Save</button>
                </span>
              ) : del === row.id ? (
                <span className="row-wrap">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDel(null)}>Cancel</button>
                  <button type="button" className="btn btn-danger btn-sm" disabled={write.isPending} onClick={() => write.mutate({ path: `/admin/ai/prices/${row.id}/`, method: 'DELETE' }, { onSettled: () => setDel(null) })}>Delete</button>
                </span>
              ) : (
                <span className="row-wrap">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEdit({ ...edit, [row.id]: { input: String(row.input_per_m_usd), output: String(row.output_per_m_usd) } })}>Edit</button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDel(row.id)}>Delete…</button>
                </span>
              )}
            </li>
          )
        })}
      </ul>
      <span className="lbl">Add a model</span>
      <div className="grid-2">
        <select aria-label="Provider" value={add.provider} onChange={(e) => setAdd({ ...add, provider: e.target.value })}>
          <option value="openai">OpenAI</option>
          <option value="gemini">Gemini</option>
        </select>
        <input aria-label="Model id" placeholder="model id" value={add.model} onChange={(e) => setAdd({ ...add, model: e.target.value })} />
        <input inputMode="decimal" aria-label="Input USD per 1M" placeholder="in $/1M" value={add.input} onChange={(e) => setAdd({ ...add, input: e.target.value })} />
        <input inputMode="decimal" aria-label="Output USD per 1M" placeholder="out $/1M" value={add.output} onChange={(e) => setAdd({ ...add, output: e.target.value })} />
      </div>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        disabled={!add.model.trim() || add.input === '' || add.output === '' || write.isPending}
        onClick={() => write.mutate(
          { path: '/admin/ai/prices/', method: 'POST', body: { provider: add.provider, model: add.model.trim(), input_per_m_usd: Number(add.input), output_per_m_usd: Number(add.output), note: '' } },
          { onSuccess: () => setAdd({ ...add, model: '', input: '', output: '' }) },
        )}
      >Add model</button>
      {write.isError && <p className="bad small">{errorText(write.error, 'Could not save (a model in use by a tier can’t be deleted).')}</p>}
    </section>
  )
}

const RANGES = ['7d', '4w', '3m', '6m', '1y'] as const

function Usage() {
  const [range, setRange] = useState<(typeof RANGES)[number]>('4w')
  const [metric, setMetric] = useState<'cost' | 'tokens'>('cost')
  const stats = useAiStats(range)
  const s = stats.data
  return (
    <div className="stack">
      <div className="segmented segmented-full" role="radiogroup" aria-label="Range">
        {RANGES.map((r) => (
          <button key={r} type="button" role="radio" aria-checked={range === r} className={`segmented-option ${range === r ? 'is-active' : ''}`} onClick={() => setRange(r)}>{r}</button>
        ))}
      </div>
      {stats.isPending && <section className="card"><Skeleton height={200} /></section>}
      {stats.isError && !s && <Forbidden error={stats.error} what="Usage" />}
      {s && (
        <div className={`stack ${stats.isPlaceholderData ? 'is-stale' : ''}`}>
          <div className="mt-grid">
            <div className="mt"><span className="lbl">Cost</span><span className="mt-value">{usd(s.totals.cost_usd)}</span><span className="mt-sub">month to date {usd(s.month.cost_usd)}</span></div>
            <div className="mt"><span className="lbl">Calls</span><span className="mt-value">{s.totals.calls.toLocaleString()}</span><span className="mt-sub">{s.totals.avg_latency_ms != null ? `avg ${(s.totals.avg_latency_ms / 1000).toFixed(1)} s` : ''}</span></div>
            <div className="mt"><span className="lbl">Tokens</span><span className="mt-value">{kTok(s.totals.input_tokens + s.totals.output_tokens)}</span><span className="mt-sub">{kTok(s.totals.input_tokens)} in · {kTok(s.totals.output_tokens)} out</span></div>
            <div className="mt"><span className="lbl">Error rate</span><span className="mt-value">{(s.totals.error_rate * 100).toFixed(1)}%</span><span className="mt-sub">{s.totals.errors} errors · {s.totals.refused} refused</span></div>
          </div>
          <section className="card stack-sm">
            <div className="kit-head">
              <span className="grow kit-title">Per day</span>
              <div className="segmented segmented-compact" role="radiogroup" aria-label="Chart metric">
                {(['cost', 'tokens'] as const).map((k) => (
                  <button key={k} type="button" role="radio" aria-checked={metric === k} className={`segmented-option ${metric === k ? 'is-active' : ''}`} onClick={() => setMetric(k)}>{k === 'cost' ? 'Cost' : 'Tokens'}</button>
                ))}
              </div>
            </div>
            <DayChart s={s} metric={metric} />
          </section>
          <Breakdown title="By tier" rows={s.by_tier.map((r) => ({ name: r.tier, ...r }))} />
          <Breakdown title="By feature" rows={s.by_operation.map((r) => ({ name: `${r.operation} · ${r.tier}`, ...r }))} />
          <Breakdown title="By user" rows={s.by_user.map((r) => ({ ...r, name: r.name }))} />
          <Breakdown title="By model" rows={s.by_model.map((r) => ({ name: `${r.model} · ${r.provider}${r.avg_latency_ms != null ? ` · ${(r.avg_latency_ms / 1000).toFixed(1)} s` : ''}`, ...r }))} />
          {s.recent_errors.length > 0 && (
            <Disclosure id="admin-errors" title="Recent errors" sub={`${s.recent_errors.length} · latest ${when(s.recent_errors[0].at)}`}>
              <section className="card">
                <ul className="admin-list">
                  {s.recent_errors.map((e, i) => (
                    <li key={i}>
                      <span className="grow">
                        <b>{e.operation}</b> <span className="muted small">{e.provider} · {e.model} · {e.status}</span>
                        <span className="small block">{e.error}</span>
                        <span className="muted small">{when(e.at)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            </Disclosure>
          )}
        </div>
      )}
    </div>
  )
}

function DayChart({ s, metric }: { s: AiStats; metric: 'cost' | 'tokens' }) {
  const data = useMemo(() => s.by_day.map((d) => ({ date: d.date, cost: d.cost_usd, input: d.input_tokens, output: d.output_tokens, errors: d.errors })), [s])
  const Tip = chartTip((items, label) => {
    const p = items[0]?.payload as (typeof data)[number] | undefined
    if (!p) return null
    return {
      title: day(label),
      lines: metric === 'cost'
        ? [{ text: usd(num(p.cost)), color: 'var(--run)' }, { text: `${p.errors} errors` }]
        : [{ text: `${kTok(p.input)} in`, color: 'var(--run)' }, { text: `${kTok(p.output)} out`, color: 'var(--sleep)' }],
    }
  })
  return (
    <div className="chart" style={{ height: 180 }} role="img" aria-label={`${metric === 'cost' ? 'Cost' : 'Tokens'} per day`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 4" />
          <XAxis dataKey="date" tickFormatter={(v: string) => day(v).replace(/ \d\d$/, '')} axisLine={false} tickLine={false} minTickGap={28} />
          <YAxis orientation="right" axisLine={false} tickLine={false} width={44} tickCount={4} tickFormatter={(v: number) => (metric === 'cost' ? `$${v.toFixed(2)}` : kTok(v))} />
          <Tooltip content={<Tip />} cursor={{ fill: 'var(--line-soft)' }} {...TIP} />
          {metric === 'cost'
            ? <Bar dataKey="cost" fill="var(--run)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
            : (
              <>
                <Bar dataKey="input" stackId="t" fill="var(--run)" isAnimationActive={false} />
                <Bar dataKey="output" stackId="t" fill="var(--sleep)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </>
            )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function Breakdown({ title, rows }: { title: string; rows: Array<{ name: string; calls: number; errors: number; cost_usd: number; input_tokens: number; output_tokens: number }> }) {
  if (!rows.length) return null
  const max = Math.max(...rows.map((r) => r.cost_usd), 0.0001)
  const sorted = [...rows].sort((a, b) => b.cost_usd - a.cost_usd)
  return (
    <Disclosure id={`admin-${title}`} title={title} sub={`${sorted[0].name} leads · ${usd(sorted[0].cost_usd)}`}>
      <section className="card">
        <ul className="admin-list">
          {sorted.map((r) => (
            <li key={r.name} className="admin-break">
              <span className="grow">
                <span className="kit-head"><b className="grow">{r.name}</b><span>{usd(r.cost_usd)}</span></span>
                <Meter value={r.cost_usd} max={max} topic="run" label={`${r.name} cost`} />
                <span className="muted small">{r.calls} calls · {kTok(r.input_tokens + r.output_tokens)} tokens{r.errors ? ` · ${r.errors} errors` : ''}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </Disclosure>
  )
}

// --- system -----------------------------------------------------------------------------

function SystemTab() {
  const sys = useAdminSystem()
  if (sys.isPending) return <section className="card"><Skeleton lines={6} /></section>
  if (sys.isError) return <Forbidden error={sys.error} what="System" />
  const s = sys.data
  const g = s.garmin
  const k = s.kubernetes
  const b = s.backups
  return (
    <div className="stack">
      <section className="card stack-sm">
        <CardHead title="At a glance" sub={`Checked ${when(s.checked_at)}`} />
        <dl className="admin-dl">
          <div><dt>Version</dt><dd className="mono">{s.version?.git_sha ? s.version.git_sha.slice(0, 7) : '—'}</dd></div>
          <div><dt>Garmin</dt><dd>{g ? (g.breaker_open ? <Pill topic="bad">Breaker open</Pill> : <Pill topic="ok">OK</Pill>) : '—'}</dd></div>
          <div><dt>Last backup</dt><dd>{b ? (b.last_success_at ? when(b.last_success_at) : b.reason ?? 'none yet') : '—'}</dd></div>
          <div><dt>GCP trial</dt><dd>{s.gcp?.configured ? `${s.gcp.days_left ?? '—'} days left${s.gcp.trial_end ? ` (ends ${day(s.gcp.trial_end)})` : ''}${s.gcp.credit_inr != null ? ` · ₹${s.gcp.credit_inr.toLocaleString('en-IN')} credit` : ''}` : 'not configured'}</dd></div>
        </dl>
      </section>

      {g && (
        <Disclosure id="sys-garmin" title="Garmin sync" sub={g.breaker_open ? `Breaker open${g.reason ? ` · ${g.reason}` : ''}` : `${g.users.filter((u) => u.connected).length} linked users`}>
          <section className="card">
            {g.breaker_open && <p className="bad small">{g.reason ?? 'Paused'}{g.retry_after_s != null ? ` · retry in ${Math.ceil(g.retry_after_s / 60)} min` : ''}</p>}
            <ul className="admin-list">
              {g.users.map((u) => (
                <li key={u.athlete_id}>
                  <span className="grow"><b>{u.name}</b>
                    <span className="muted small block">{u.connected ? `last sync ${when(u.last_sync)}${u.hours_since_sync != null ? ` · ${u.hours_since_sync.toFixed(1)} h ago` : ''}${u.backfilled ? ' · backfilled' : ''}` : 'not linked'}</span>
                  </span>
                  {u.connected && u.hours_since_sync != null && u.hours_since_sync > 24 && <Pill topic="bad">Stale</Pill>}
                </li>
              ))}
            </ul>
          </section>
        </Disclosure>
      )}

      {s.celery && (
        <Disclosure id="sys-queues" title="Queues" sub={s.celery.available ? s.celery.queues.map((q) => `${q.name} ${q.length}`).join(' · ') : 'unavailable'}>
          <section className="card">
            <ul className="admin-list">{s.celery.queues.map((q) => <li key={q.name}><span className="grow">{q.name}</span><b>{q.length}</b></li>)}</ul>
          </section>
        </Disclosure>
      )}

      {b && (
        <Disclosure id="sys-backups" title="Backups" sub={b.available ? `${b.schedule ?? ''} · R2 ${b.r2?.configured ? 'on' : 'off'}` : b.reason ?? 'unavailable'}>
          <section className="card stack-sm">
            {b.r2?.note && <p className="muted small">R2: {b.r2.note}</p>}
            <ul className="admin-list">
              {b.jobs.map((j) => (
                <li key={j.name}>
                  <span className="grow"><b className="mono small">{j.name}</b><span className="muted small block">{when(j.started_at)} → {when(j.finished_at)}</span></span>
                  <Pill topic={j.status === 'succeeded' ? 'ok' : j.status === 'failed' ? 'bad' : undefined}>{j.status}</Pill>
                </li>
              ))}
            </ul>
          </section>
        </Disclosure>
      )}

      {k && (
        <Disclosure id="sys-k8s" title="Server" sub={k.available ? `${k.nodes.length} node${k.nodes.length === 1 ? '' : 's'} · ${k.pods.length} pods` : `unavailable (${k.reason ?? 'error'})`}>
          {k.nodes.map((n) => (
            <section key={n.name} className="card stack-sm">
              <div className="kit-head"><b className="grow">{n.name}</b>{n.ready ? <Pill topic="ok">Ready</Pill> : <Pill topic="bad">Not ready</Pill>}</div>
              <NodeBar label="CPU" pct={n.cpu_pct} text={n.cpu_used_cores != null ? `${n.cpu_used_cores.toFixed(1)} of ${n.cpu_cores} cores` : `${n.cpu_cores} cores`} />
              <NodeBar label="Memory" pct={n.memory_pct} text={`${gb(n.memory_used_bytes)} of ${gb(n.memory_bytes)}`} />
              {n.disk_bytes != null && (
                <NodeBar
                  label="Disk"
                  pct={n.disk_allocatable_bytes != null ? Math.round(100 - (n.disk_allocatable_bytes / n.disk_bytes) * 100) : null}
                  text={`${gb(n.disk_allocatable_bytes)} free of ${gb(n.disk_bytes)}`}
                />
              )}
            </section>
          ))}
          <section className="card">
            <ul className="admin-list">
              {k.pods.map((p) => (
                <li key={p.name}>
                  <span className="grow"><b className="mono small">{p.name}</b><span className="muted small block">{p.phase} · {p.restarts} restarts · since {when(p.started_at)}</span></span>
                  {p.ready ? <Pill topic="ok">Ready</Pill> : <Pill topic="bad">{p.phase}</Pill>}
                </li>
              ))}
            </ul>
          </section>
        </Disclosure>
      )}
    </div>
  )
}

function NodeBar({ label, pct, text }: { label: string; pct: number | null; text: string }) {
  return (
    <div className="stack-sm">
      <span className="kit-head small"><span className="grow">{label}</span><span className="muted">{pct != null ? `${pct}% · ` : ''}{text}</span></span>
      {pct != null && <Meter value={pct} max={100} topic="run" over={pct >= 90} label={`${label} ${pct}%`} />}
    </div>
  )
}
