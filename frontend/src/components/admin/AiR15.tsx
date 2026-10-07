/**
 * R15 admin → AI: provider switch, model cards (what each model is, speed / quality /
 * cost, status), per-tier primary + fallback pickers, and Compare (2–4 models side by
 * side). Lives in the admin chunk only.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, json } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { useAdminUsers, useAdminWrite, useAiConfig, useAiProviders, type AiProvider } from '../../lib/r14admin'
import {
  STATUS_TEXT, useCompareHistory, useModelCards,
  type CompareRun, type ConfigR15, type ModelCard, type ModelStatus, type SwitchResult, type TierKey, type TierR15,
} from '../../lib/r15admin'
import { BottomSheet } from '../BottomSheet'
import { CheckIcon, ChevronDown, CloseIcon, PlusIcon, RefreshIcon } from '../Icons'
import { Pill } from '../Kit'
import { Skeleton } from '../States'
import '../../styles/r15admin.css'

const TIERS: TierKey[] = ['lite', 'fast', 'coach', 'deep']
const TIER_TEXT: Record<TierKey, string> = { lite: 'Lite', fast: 'Fast', coach: 'Coach', deep: 'Deep' }

const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'never'
export const usdFine = (v: number | null | undefined) =>
  v == null ? '—' : v === 0 ? '$0' : v < 0.001 ? `$${v.toFixed(5)}` : v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(3)}`
const per1m = (v: number | null | undefined) => (v == null ? '—' : `$${v > 0 && v < 0.1 ? v.toFixed(3) : v.toFixed(2)}`)
const secs = (ms: number | null | undefined) => (ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`)

export function StatusChip({ status, checked }: { status: ModelStatus | undefined; checked?: string | null }) {
  const s = status ?? 'unknown'
  const topic = s === 'ok' ? 'ok' : s === 'busy' ? 'habits' : s === 'unknown' ? undefined : 'bad'
  return (
    <span title={checked !== undefined ? `Last checked ${when(checked)}` : undefined}>
      <Pill topic={topic}>{STATUS_TEXT[s]}</Pill>
    </span>
  )
}

const LEVEL = {
  speed: { slow: 1, medium: 2, fast: 3 } as Record<string, number>,
  quality: { basic: 1, good: 2, strong: 3, best: 4 } as Record<string, number>,
  cost: { free_tier: 1, $: 2, $$: 3, $$$: 4 } as Record<string, number>,
}
const LEVEL_WORD = {
  speed: { slow: 'Slow', medium: 'Medium', fast: 'Fast' } as Record<string, string>,
  quality: { basic: 'Basic', good: 'Good', strong: 'Strong', best: 'Best' } as Record<string, string>,
  cost: { free_tier: 'Free tier', $: 'Cheap', $$: 'Mid', $$$: 'Pricey' } as Record<string, string>,
}

function Dots({ label, value, max, word, kind }: { label: string; value: number; max: number; word: string; kind: 'good' | 'cost' }) {
  return (
    <div className="ai-meter" aria-label={`${label}: ${word}`}>
      <span className="ai-meter-label">{label}</span>
      <span className={`ai-dots is-${kind}`} aria-hidden="true">
        {Array.from({ length: max }, (_, i) => <i key={i} className={i < value ? 'on' : ''} />)}
      </span>
      <span className="ai-meter-word">{word}</span>
    </div>
  )
}

function Meters({ m }: { m: ModelCard }) {
  return (
    <div className="ai-meters">
      <Dots label="Speed" value={LEVEL.speed[m.speed] ?? 0} max={3} word={LEVEL_WORD.speed[m.speed] ?? '—'} kind="good" />
      <Dots label="Quality" value={LEVEL.quality[m.quality] ?? 0} max={4} word={LEVEL_WORD.quality[m.quality] ?? '—'} kind="good" />
      <Dots label="Cost" value={LEVEL.cost[m.cost_level] ?? 0} max={4} word={LEVEL_WORD.cost[m.cost_level] ?? '—'} kind="cost" />
    </div>
  )
}

export function Glossary() {
  return (
    <p className="muted small ai-glossary">
      <b>Tokens</b> are the small chunks of text a model reads (input) and writes (output) — roughly ¾ of a word each.
      Prices are <b>per 1M tokens</b> (one million ≈ 750,000 words), so one coach reply of a few thousand tokens costs a fraction of a cent.
    </p>
  )
}

// --- provider switch ------------------------------------------------------------------

export function ProviderSwitch() {
  const providers = useAiProviders()
  const cfg = useAiConfig()
  const client = useQueryClient()
  const configured = (providers.data ?? []).filter((p) => p.configured)
  const tiers = (cfg.data?.tiers ?? []) as TierR15[]
  const current = tiers.length && tiers.every((t) => t.provider === tiers[0].provider) ? tiers[0].provider : null
  const [pick, setPick] = useState<string>('')
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<SwitchResult | null>(null)
  const [err, setErr] = useState('')
  const sel = pick || current || configured[0]?.key || ''
  if (providers.isPending || cfg.isPending) return <section className="card"><Skeleton lines={2} /></section>
  if (!configured.length) return null
  const label = (k: string) => (k === 'gemini' ? 'Google Gemini' : configured.find((p) => p.key === k)?.label ?? k)
  const go = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await api<SwitchResult>('/admin/ai/config/switch/', { method: 'POST', ...json({ provider: sel }) })
      setOut(r)
      setConfirm(false)
      client.setQueryData(['admin', 'ai-config'], { tiers: r.tiers, operations: r.operations })
      client.invalidateQueries({ queryKey: ['admin'] })
    } catch (e) {
      setErr(errorText(e, 'Could not switch.'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="card stack-sm ai-switch">
      <div className="kit-head">
        <span className="grow kit-title">Provider</span>
        <span className="muted small">{current ? `All tiers on ${label(current)}` : 'Mixed per tier'}</span>
      </div>
      <div className="segmented segmented-full" role="radiogroup" aria-label="Provider">
        {configured.map((p) => (
          <button key={p.key} type="button" role="radio" aria-checked={sel === p.key} className={`segmented-option ${sel === p.key ? 'is-active' : ''}`}
            onClick={() => { setPick(p.key); setConfirm(false); setOut(null) }}>
            {label(p.key)}
          </button>
        ))}
      </div>
      {confirm ? (
        <div className="confirm-row">
          <span className="grow small">Point lite, fast, coach and deep at {label(sel)}’s recommended models? Fallbacks stay as they are.</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(false)}>Cancel</button>
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={go}>{busy ? 'Switching…' : 'Switch'}</button>
        </div>
      ) : (
        <button type="button" className="btn btn-primary btn-sm" disabled={current === sel} onClick={() => setConfirm(true)}>
          {current === sel ? `Already using ${label(sel)}` : `Use ${label(sel)} for all tiers…`}
        </button>
      )}
      {err && <p className="bad small">{err}</p>}
      {out && (
        <div className="small stack-sm" role="status">
          {out.changed.length > 0 && <p>Changed: {out.changed.map((c) => `${c.tier} → ${c.model}`).join(' · ')}</p>}
          {out.unchanged.length > 0 && <p className="muted">Unchanged: {out.unchanged.map((c) => `${c.tier} (${c.reason})`).join(' · ')}</p>}
        </div>
      )}
    </section>
  )
}

// --- model cards ----------------------------------------------------------------------

function ModelCardView({ m, provider }: { m: ModelCard; provider: AiProvider | undefined }) {
  return (
    <article className="card stack-sm ai-model">
      <div className="kit-head">
        <span className="grow">
          <b className="ai-model-name">{m.label || m.id}</b>
          <span className="muted small block">{provider?.key === 'gemini' ? 'Google Gemini' : provider?.label ?? ''} · <code>{m.id}</code></span>
          <span className="muted small block">Checked {when(m.checked_at)}</span>
        </span>
        <StatusChip status={m.status} checked={m.checked_at} />
      </div>
      {m.note && m.status !== 'ok' && <p className="small warn-text">{m.note}</p>}
      <p className="small">{m.summary}</p>
      <div className="row-wrap ai-chips">
        {m.best_for.length > 0 && <span className="muted small">Best for</span>}
        {m.best_for.map((t) => <Pill key={t} topic="run">{TIER_TEXT[t] ?? t}</Pill>)}
        {m.free_tier_ok === true && <Pill topic="ok">Free tier OK</Pill>}
        {m.free_tier_ok === false && <Pill topic="bad">Not on free tier</Pill>}
      </div>
      <Meters m={m} />
      <dl className="ai-facts">
        <div><dt>Price / 1M</dt><dd>{per1m(m.price_in_per_1m)} in · {per1m(m.price_out_per_1m)} out</dd></div>
        {m.context_window != null && <div><dt>Context</dt><dd>{m.context_window >= 1e6 ? `${(m.context_window / 1e6).toFixed(1)}M` : `${Math.round(m.context_window / 1000)}k`} tokens</dd></div>}
        <div><dt>Est. per call</dt><dd>{TIERS.map((t) => `${TIER_TEXT[t]} ${usdFine(m.est_cost_per_call_usd?.[t])}`).join(' · ')}</dd></div>
        <div><dt>Our 30 days</dt><dd>{m.calls ? `${m.calls} calls · avg ${secs(m.avg_latency_ms)} · ${Math.round(m.error_rate * 100)}% errors · ${usdFine(m.avg_cost_usd)}/call` : 'Not used yet'}</dd></div>
      </dl>
      {!m.priced && <p className="muted small">Not in the price table yet — costs show as —.</p>}
    </article>
  )
}

export function ModelsSection() {
  const providers = useAiProviders()
  const configured = (providers.data ?? []).filter((p) => p.configured)
  const [prov, setProv] = useState('')
  const p = prov || configured[0]?.key || ''
  const [polling, setPolling] = useState(0)
  const cards = useModelCards(p, polling > Date.now())
  const client = useQueryClient()
  const [check, setCheck] = useState<{ busy: boolean; msg: string }>({ busy: false, msg: '' })
  const [filter, setFilter] = useState<'all' | 'ok'>('all')
  useEffect(() => {
    if (!polling) return
    const t = setTimeout(() => setPolling(0), Math.max(0, polling - Date.now()))
    return () => clearTimeout(t)
  }, [polling])
  if (providers.isPending) return <Skeleton lines={3} />
  const runCheck = async (force: boolean) => {
    setCheck({ busy: true, msg: '' })
    try {
      const r = await api<{ queued: string[]; skipped: string[] }>('/admin/ai/models/check/', { method: 'POST', ...json({ provider: p, force }) })
      setCheck({
        busy: false,
        msg: r.queued.length
          ? `Checking ${r.queued.length} model${r.queued.length === 1 ? '' : 's'} (about ${Math.ceil(r.queued.length * 1.5 + 3)} s)…${r.skipped.length ? ` ${r.skipped.length} checked in the last 24 h were skipped.` : ''}`
          : `Nothing to check — all ${r.skipped.length} were checked in the last 24 h.`,
      })
      if (r.queued.length) setPolling(Date.now() + Math.max(20_000, r.queued.length * 2500 + 10_000))
    } catch (e) {
      setCheck({ busy: false, msg: errorText(e, 'Could not start the check.') })
    }
  }
  const list = (cards.data?.models ?? []).filter((m) => filter === 'all' || m.status === 'ok')
  return (
    <div className="stack">
      <div className="segmented segmented-full" role="radiogroup" aria-label="Provider">
        {configured.map((x) => (
          <button key={x.key} type="button" role="radio" aria-checked={p === x.key} className={`segmented-option ${p === x.key ? 'is-active' : ''}`} onClick={() => setProv(x.key)}>
            {x.key === 'gemini' ? 'Google Gemini' : x.label}
          </button>
        ))}
      </div>
      <section className="card stack-sm">
        <p className="muted small">
          {cards.data ? `${cards.data.models.length} models · ${cards.data.source === 'live' ? 'live list' : 'price table (live list unavailable)'} · fetched ${when(cards.data.fetched_at)}` : ' '}
        </p>
        <div className="row-wrap">
          <button type="button" className="btn btn-secondary btn-sm" disabled={check.busy || !p} onClick={() => runCheck(false)}>
            <CheckIcon size={16} /> {check.busy ? 'Starting…' : 'Check models'}
          </button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={check.busy || !p} onClick={() => runCheck(true)}>Re-check all</button>
          <button type="button" className="btn btn-ghost btn-sm" aria-label="Refresh model list" disabled={cards.isFetching}
            onClick={() => api(`/admin/ai/models/?provider=${p}&refresh=1`).then((d) => client.setQueryData(['admin', 'models', p], d)).catch(() => undefined)}>
            <RefreshIcon size={16} /> Refresh list
          </button>
        </div>
        {check.msg && <p className="small" role="status">{check.msg}{polling > Date.now() ? ' Updating…' : ''}</p>}
        <p className="muted small">A check sends each model one tiny prompt (“Reply with OK.”) — about $0.00001 each.</p>
      </section>
      <div className="segmented segmented-full" role="radiogroup" aria-label="Show">
        {(['all', 'ok'] as const).map((f) => (
          <button key={f} type="button" role="radio" aria-checked={filter === f} className={`segmented-option ${filter === f ? 'is-active' : ''}`} onClick={() => setFilter(f)}>
            {f === 'all' ? 'All models' : 'Working only'}
          </button>
        ))}
      </div>
      {cards.isPending ? <Skeleton lines={4} /> : cards.isError ? (
        <p className="bad small">{errorText(cards.error, 'Models did not load.')}</p>
      ) : (
        <div className="ai-model-grid">
          {list.map((m) => <ModelCardView key={m.id} m={m} provider={configured.find((x) => x.key === p)} />)}
          {!list.length && <p className="muted small">No models to show.</p>}
        </div>
      )}
    </div>
  )
}

// --- model picker sheet ---------------------------------------------------------------

/** A button that opens a sheet listing the provider's models with their summary and cost. */
export function ModelPicker({ provider, value, onChange, tier, label, allowNone }: {
  provider: string; value: string | null; onChange: (model: string | null) => void; tier?: TierKey; label: string; allowNone?: string
}) {
  const [open, setOpen] = useState(false)
  const cards = useModelCards(open || !!value ? provider : '')
  const cur = cards.data?.models.find((m) => m.id === value)
  const list = useMemo(() => {
    const ms = cards.data?.models ?? []
    // Suited to this tier first, then working ones.
    const rank = (m: ModelCard) => (tier && m.best_for.includes(tier) ? 0 : 2) + (m.status === 'ok' ? 0 : m.status === 'unknown' ? 0.5 : 1)
    return [...ms].sort((a, b) => rank(a) - rank(b))
  }, [cards.data, tier])
  return (
    <div className="ai-picker-wrap">
      <button type="button" className="ai-picker" aria-label={`${label}: ${value ?? allowNone ?? 'none'}`} onClick={() => setOpen(true)} disabled={!provider}>
        <span className="grow">
          <b>{value ? cur?.label || value : allowNone ?? 'Pick a model'}</b>
          {cur && (
            <span className="muted small block">
              {LEVEL_WORD.speed[cur.speed]} · {LEVEL_WORD.cost[cur.cost_level]}{tier ? ` · ~${usdFine(cur.est_cost_per_call_usd?.[tier])}/call` : ''}
            </span>
          )}
        </span>
        <ChevronDown size={18} className="muted" />
      </button>
      {cur && cur.status !== 'ok' && cur.status !== 'unknown' && (
        <p className="small warn-text">{cur.note || `This model was ${STATUS_TEXT[cur.status].toLowerCase()} at the last check — calls may fail and use the fallback.`}</p>
      )}
      <BottomSheet open={open} onClose={() => setOpen(false)} title={label}>
        <div className="stack-sm">
          {allowNone && (
            <button type="button" className={`ai-pick-row ${value == null ? 'is-active' : ''}`} onClick={() => { onChange(null); setOpen(false) }}>
              <span className="grow"><b>{allowNone}</b></span>
              {value == null && <CheckIcon size={18} />}
            </button>
          )}
          {cards.isPending && <Skeleton lines={4} />}
          {cards.isError && <p className="bad small">{errorText(cards.error, 'Models did not load.')}</p>}
          {list.map((m) => (
            <button key={m.id} type="button" className={`ai-pick-row ${m.id === value ? 'is-active' : ''}`} onClick={() => { onChange(m.id); setOpen(false) }}>
              <span className="grow">
                <span className="kit-head">
                  <b className="grow">{m.label || m.id}</b>
                  <StatusChip status={m.status} checked={m.checked_at} />
                </span>
                <span className="muted small block">{m.summary}</span>
                <span className="small block ai-pick-meta">
                  {LEVEL_WORD.speed[m.speed]} · {LEVEL_WORD.quality[m.quality]} quality · {LEVEL_WORD.cost[m.cost_level]}
                  {tier ? ` · ~${usdFine(m.est_cost_per_call_usd?.[tier])}/call` : ` · ${per1m(m.price_in_per_1m)} / ${per1m(m.price_out_per_1m)} per 1M`}
                  {tier && m.best_for.includes(tier) ? ' · suits this tier' : ''}
                </span>
                {m.note && m.status !== 'ok' && <span className="small block warn-text">{m.note}</span>}
              </span>
              {m.id === value && <CheckIcon size={18} />}
            </button>
          ))}
        </div>
      </BottomSheet>
    </div>
  )
}

// --- tiers (primary + fallback) ---------------------------------------------------------

type Draft = { provider: string; model: string; fallback_provider: string | null; fallback_model: string | null }

export function TiersR15() {
  const cfg = useAiConfig()
  const providers = useAiProviders()
  const write = useAdminWrite<ConfigR15>()
  const [draft, setDraft] = useState<Record<string, Draft>>({})
  if (cfg.isPending || providers.isPending) return <Skeleton lines={4} />
  if (cfg.isError) return <p className="bad small">{errorText(cfg.error, 'AI config did not load.')}</p>
  const configured = (providers.data ?? []).filter((p) => p.configured)
  const tiers = cfg.data.tiers as TierR15[]
  const value = (t: TierR15): Draft => draft[t.tier] ?? { provider: t.provider, model: t.model, fallback_provider: t.fallback_provider ?? null, fallback_model: t.fallback_model ?? null }
  const changed = Object.entries(draft).filter(([tier, v]) => {
    const t = tiers.find((x) => x.tier === tier)
    return t && (t.provider !== v.provider || t.model !== v.model || (t.fallback_provider ?? null) !== v.fallback_provider || (t.fallback_model ?? null) !== v.fallback_model)
  })
  const edit = (tier: string, cur: Draft, patch: Partial<Draft>) => setDraft({ ...draft, [tier]: { ...cur, ...patch } })
  const save = () =>
    write.mutate({ path: '/admin/ai/config/', method: 'PUT', body: { tiers: changed.map(([tier, v]) => ({ tier, ...v })) } }, { onSuccess: () => setDraft({}) })
  const provLabel = (k: string) => (k === 'gemini' ? 'Gemini' : configured.find((p) => p.key === k)?.label ?? k)
  return (
    <section className="card stack">
      {tiers.map((t) => {
        const v = value(t)
        const tk = t.tier as TierKey
        return (
          <div key={t.tier} className="stack-sm admin-tier">
            <div className="kit-head">
              <span className="grow"><b>{t.tier}</b> <span className="muted small">{t.source === 'db' ? `set here${t.updated_at ? ` · ${when(t.updated_at)}` : ''}` : 'from env'}</span></span>
              {t.model_status && t.model_status !== 'unknown' && <StatusChip status={t.model_status} />}
              {!t.available && <Pill topic="bad">Unavailable</Pill>}
            </div>
            <div className="ai-route">
              <select aria-label={`${t.tier} provider`} value={v.provider} onChange={(e) => edit(t.tier, v, { provider: e.target.value, model: '' })}>
                {configured.map((p) => <option key={p.key} value={p.key}>{provLabel(p.key)}</option>)}
                {!configured.some((p) => p.key === v.provider) && <option value={v.provider}>{v.provider} (no key)</option>}
              </select>
              <ModelPicker provider={v.provider} value={v.model || null} tier={tk} label={`${t.tier} model`} onChange={(m) => m && edit(t.tier, v, { model: m })} />
            </div>
            {t.warning && <p className="small warn-text">{t.warning}</p>}
            <span className="muted small ai-fallback-label">If it fails, fall back to</span>
            <div className="ai-route">
              <select aria-label={`${t.tier} fallback provider`} value={v.fallback_provider ?? ''}
                onChange={(e) => edit(t.tier, v, e.target.value ? { fallback_provider: e.target.value, fallback_model: '' } : { fallback_provider: null, fallback_model: null })}>
                <option value="">Default</option>
                {configured.map((p) => <option key={p.key} value={p.key}>{provLabel(p.key)}</option>)}
              </select>
              {v.fallback_provider ? (
                <ModelPicker provider={v.fallback_provider} value={v.fallback_model || null} tier={tk} label={`${t.tier} fallback model`} onChange={(m) => m && edit(t.tier, v, { fallback_model: m })} />
              ) : (
                <span className="muted small ai-fallback-note">
                  {t.fallback ? `Now: ${provLabel(t.fallback.provider)} · ${t.fallback.model}` : 'No fallback (same as primary or no key)'}
                </span>
              )}
            </div>
            {t.source === 'db' && (
              <button type="button" className="link-btn small" disabled={write.isPending} onClick={() => write.mutate({ path: '/admin/ai/config/', method: 'PUT', body: { tiers: [{ tier: t.tier, reset: true }] } })}>
                Reset to env ({t.env_provider} · {t.env_model})
              </button>
            )}
          </div>
        )
      })}
      <p className="muted small">If a model is busy it is retried twice, then the call goes once to the fallback.</p>
      <p className="muted small">Uses: {Object.entries(cfg.data.operations).map(([op, tier]) => `${op} → ${tier}`).join(' · ')}</p>
      {write.isError && <p className="bad small">{errorText(write.error, 'Could not save.')}</p>}
      <button type="button" className="btn btn-primary btn-sm" disabled={!changed.length || write.isPending || changed.some(([, v]) => !v.model || (v.fallback_provider != null && !v.fallback_model))} onClick={save}>
        {write.isPending ? 'Saving…' : changed.length ? `Save ${changed.length} change${changed.length === 1 ? '' : 's'}` : 'No changes'}
      </button>
    </section>
  )
}

// --- compare ------------------------------------------------------------------------------

type Target = { provider: string; model: string }
const OPS: Array<{ value: '' | 'insights_summary' | 'run_review'; label: string }> = [
  { value: '', label: 'My prompt' }, { value: 'insights_summary', label: 'Replay Insights' }, { value: 'run_review', label: 'Replay run review' },
]

export function Compare() {
  const providers = useAiProviders()
  const users = useAdminUsers()
  const history = useCompareHistory()
  const client = useQueryClient()
  const configured = (providers.data ?? []).filter((p) => p.configured)
  const first = configured[0]?.key ?? ''
  const second = configured[1]?.key ?? first
  const [targets, setTargets] = useState<Target[]>([{ provider: first, model: '' }, { provider: second, model: '' }])
  const [op, setOp] = useState<'' | 'insights_summary' | 'run_review'>('')
  const [athlete, setAthlete] = useState('')
  const [prompt, setPrompt] = useState('In two sentences, how should a beginner pace a first 10K?')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [run, setRun] = useState<CompareRun | null>(null)

  useEffect(() => {
    // Providers arrive after first render: fill empty provider slots.
    if (first) setTargets((ts) => ts.map((t, i) => (t.provider ? t : { provider: i === 1 ? second : first, model: '' })))
  }, [first, second])

  if (providers.isPending) return <Skeleton lines={3} />
  const dup = new Set(targets.map((t) => `${t.provider}/${t.model}`)).size !== targets.length
  const ready = targets.every((t) => t.provider && t.model) && !dup && (op ? true : prompt.trim().length > 0)
  const go = async () => {
    setBusy(true)
    setErr('')
    try {
      const body: Record<string, unknown> = { targets }
      if (prompt.trim()) body.prompt = prompt.trim()
      if (op) body.operation = op
      if (op && athlete) body.athlete_id = Number(athlete)
      const r = await api<CompareRun>('/admin/ai/compare/', { method: 'POST', ...json(body) })
      setRun(r)
      client.invalidateQueries({ queryKey: ['admin', 'compare'] })
    } catch (e) {
      setErr(errorText(e, 'Compare failed.'))
    } finally {
      setBusy(false)
    }
  }
  const set = (i: number, t: Target) => setTargets(targets.map((x, j) => (j === i ? t : x)))
  return (
    <div className="stack">
      <section className="card stack-sm">
        <h3 className="ai-h">Models ({targets.length} of 4)</h3>
        {targets.map((t, i) => (
          <div key={i} className="ai-target">
            <span className="ai-target-n" aria-hidden="true">{String.fromCharCode(65 + i)}</span>
            <select aria-label={`Model ${i + 1} provider`} value={t.provider} onChange={(e) => set(i, { provider: e.target.value, model: '' })}>
              {configured.map((p) => <option key={p.key} value={p.key}>{p.key === 'gemini' ? 'Gemini' : p.label}</option>)}
            </select>
            <div className="ai-target-pick"><ModelPicker provider={t.provider} value={t.model || null} label={`Model ${String.fromCharCode(65 + i)}`} onChange={(m) => m && set(i, { ...t, model: m })} /></div>
            {targets.length > 2 && (
              <button type="button" className="chip" aria-label={`Remove model ${i + 1}`} onClick={() => setTargets(targets.filter((_, j) => j !== i))}><CloseIcon size={18} /></button>
            )}
          </div>
        ))}
        {dup && <p className="bad small">Pick different models — each one once.</p>}
        {targets.length < 4 && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTargets([...targets, { provider: first, model: '' }])}><PlusIcon size={16} /> Add a model</button>
        )}
      </section>
      <section className="card stack-sm">
        <h3 className="ai-h">Prompt</h3>
        <div className="segmented segmented-full" role="radiogroup" aria-label="What to send">
          {OPS.map((o) => (
            <button key={o.value} type="button" role="radio" aria-checked={op === o.value} className={`segmented-option ${op === o.value ? 'is-active' : ''}`} onClick={() => setOp(o.value)}>{o.label}</button>
          ))}
        </div>
        {op && (
          <>
            <p className="muted small">
              {op === 'insights_summary' ? 'Sends the same 4-week aggregates the Insights summary uses' : 'Sends the newest run review’s comparison rows and bullets'} — no names, notes or private habits.
            </p>
            <select aria-label="Whose data" value={athlete} onChange={(e) => setAthlete(e.target.value)}>
              <option value="">My own data</option>
              {(users.data?.users ?? []).map((u) => <option key={u.id} value={u.id}>{u.display_name || u.username}</option>)}
            </select>
          </>
        )}
        <textarea aria-label={op ? 'Extra instruction (optional)' : 'Prompt'} rows={4} maxLength={4000} value={prompt}
          placeholder={op ? 'Optional extra instruction' : 'Ask anything'} onChange={(e) => setPrompt(e.target.value)} />
        <button type="button" className="btn btn-primary" disabled={busy || !ready} onClick={go}>
          {busy ? `Running ${targets.length} models…` : `Run on ${targets.length} models`}
        </button>
        {busy && <p className="muted small">They run one after another; this can take up to a minute.</p>}
        {err && <p className="bad small">{err}</p>}
      </section>
      {run && <CompareView run={run} onChange={setRun} />}
      <section className="card stack-sm">
        <h3 className="ai-h">History</h3>
        {history.isPending ? <Skeleton lines={3} /> : !history.data?.length ? <p className="muted small">No runs yet.</p> : (
          <div className="ai-history">
            {history.data.map((h) => (
              <button key={h.id} type="button" className={`ai-history-row ${run?.id === h.id ? 'is-active' : ''}`} onClick={() => setRun(h)}>
                <span className="grow">
                  <b className="ai-clip">{h.operation ? OPS.find((o) => o.value === h.operation)?.label : h.prompt}</b>
                  <span className="muted small block">
                    {when(h.created_at)} · {h.results.map((r) => `${r.model}${r.rating ? ` ${r.rating}★` : ''}${r.ok ? '' : ' ✕'}`).join(' · ')}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function CompareView({ run, onChange }: { run: CompareRun; onChange: (r: CompareRun) => void }) {
  const client = useQueryClient()
  const [err, setErr] = useState('')
  const rate = async (index: number, rating: number | null) => {
    setErr('')
    // Optimistic: show the stars at once.
    onChange({ ...run, results: run.results.map((r) => (r.index === index ? { ...r, rating } : r)) })
    try {
      onChange(await api<CompareRun>(`/admin/ai/compare/${run.id}/`, { method: 'PATCH', ...json({ ratings: [{ index, rating }] }) }))
      client.invalidateQueries({ queryKey: ['admin', 'compare'] })
    } catch (e) {
      setErr(errorText(e, 'Could not save the rating.'))
    }
  }
  const fastest = Math.min(...run.results.filter((r) => r.ok).map((r) => r.latency_ms))
  const cheapest = Math.min(...run.results.filter((r) => r.ok).map((r) => r.cost_usd))
  return (
    <section className="stack-sm">
      <div className="kit-head">
        <span className="grow kit-title">Results</span>
        <span className="muted small">{when(run.created_at)}</span>
      </div>
      {run.context_note && <p className="muted small">Context: {run.context_note}</p>}
      <details className="ai-sent">
        <summary className="small">What was sent</summary>
        <pre className="ai-pre">{run.prompt}</pre>
      </details>
      <div className="ai-compare-grid">
        {run.results.map((r) => (
          <article key={r.index} className="card stack-sm ai-result">
            <div className="kit-head">
              <span className="grow">
                <b>{String.fromCharCode(65 + r.index)} · {r.model}</b>
                <span className="muted small block">{r.provider === 'gemini' ? 'Google Gemini' : r.provider}</span>
              </span>
              {r.ok ? <Pill topic="ok">OK</Pill> : <Pill topic="bad">{r.error_kind ? STATUS_TEXT[r.error_kind as ModelStatus] ?? r.error_kind.replace('_', ' ') : 'Error'}</Pill>}
            </div>
            {r.ok ? <div className="admin-reply ai-output">{r.text}</div> : (
              <div className="stack-sm">
                <p className="bad small">{r.hint || r.error || 'Failed.'}</p>
                {r.hint && r.error && <p className="muted small ai-clip">{r.error}</p>}
              </div>
            )}
            <dl className="ai-facts ai-facts-row">
              <Fact label="Time" best={r.ok && r.latency_ms === fastest && run.results.length > 1}>{secs(r.latency_ms)}</Fact>
              <Fact label="Tokens">{r.input_tokens} in / {r.output_tokens} out</Fact>
              <Fact label="Cost" best={r.ok && r.cost_usd === cheapest && run.results.length > 1}>{usdFine(r.cost_usd)}</Fact>
            </dl>
            <div className="ai-stars" role="radiogroup" aria-label={`Rate ${r.model}`}>
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" role="radio" aria-checked={r.rating === n} aria-label={`${n} of 5`}
                  className={`ai-star ${r.rating != null && n <= r.rating ? 'on' : ''}`} onClick={() => rate(r.index, r.rating === n ? null : n)}>★</button>
              ))}
            </div>
          </article>
        ))}
      </div>
      {err && <p className="bad small">{err}</p>}
    </section>
  )
}

function Fact({ label, best, children }: { label: string; best?: boolean; children: ReactNode }) {
  return <div className={best ? 'is-best' : ''}><dt>{label}</dt><dd>{children}{best ? ' ✓' : ''}</dd></div>
}
