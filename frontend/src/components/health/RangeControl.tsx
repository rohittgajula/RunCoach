import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { addDays, todayISO } from '../../lib/format'
import { BottomSheet } from '../BottomSheet'
import { Field } from '../Field'
import { CalendarIcon } from '../Icons'
import {
  FREQ_WORD, MAX_DAYS, PRESETS, autoFreq, customError, daySpan, freqAllowed, fromSearch,
  pillText, readStored, rangeText, resolve, writeSearch, writeStored,
  type Freq, type FreqChoice, type Period, type Preset, type Selection,
} from './healthRange'

/**
 * The section's selection: URL params win (shareable / back button), then this
 * section's last choice on this device, then the section default.
 */
export function useSectionSelection(section: string, initial: Preset): [Period, (s: Selection) => void] {
  const [search, setSearch] = useSearchParams()
  const fromUrl = fromSearch(search)
  const [stored, setStored] = useState<Record<string, Selection | null>>({})
  const sel: Selection = fromUrl
    ?? (section in stored ? stored[section] : readStored(section))
    ?? { kind: 'preset', range: initial, freq: 'auto' }
  const key = JSON.stringify(sel)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const period = useMemo(() => resolve(sel), [key])

  // Arriving on a section without params: mirror its selection into the URL.
  useEffect(() => {
    if (!section || fromUrl) return
    setSearch((prev) => writeSearch(prev, sel), { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, key])

  const set = useCallback((next: Selection) => {
    writeStored(section, next)
    setStored((s) => ({ ...s, [section]: next }))
    setSearch((prev) => writeSearch(prev, next), { replace: true })
  }, [section, setSearch])

  return [period, set]
}

/** Header pill: "4w · weekly" — opens the range sheet. */
export function RangePill({ period, onClick, freq = true }: { period: Period; onClick: () => void; freq?: boolean }) {
  const custom = period.selection.kind === 'custom'
  return (
    <button type="button" className={`range-pill ${custom && freq ? 'is-two' : ''}`} onClick={onClick} aria-label={`Range: ${period.long}${freq ? `, ${FREQ_WORD[period.freq]}` : ''}. Change`}>
      <CalendarIcon size={16} />
      {custom && freq ? (
        <span className="range-pill-text"><span>{period.short}</span><small>{FREQ_WORD[period.freq]}</small></span>
      ) : (
        <span>{freq ? pillText(period) : period.short}</span>
      )}
    </button>
  )
}

type Draft = { mode: Preset | 'custom'; start: string; end: string; freq: FreqChoice }

const draftOf = (p: Period): Draft => ({
  mode: p.selection.kind === 'preset' ? p.selection.range : 'custom',
  start: p.selection.kind === 'custom' ? p.selection.start : addDays(todayISO(), -29),
  end: p.selection.kind === 'custom' ? p.selection.end : todayISO(),
  freq: p.selection.freq,
})

/**
 * Range sheet: presets 7d · 4w · 3m · 6m · 1y · Custom (from/to, ≤ 2 years, default the
 * last 30 days) and the frequency (Auto · Day · Week · Month).
 */
export function RangeSheet({
  open, onClose, period, onApply, title = 'Range', showFreq = true,
}: { open: boolean; onClose: () => void; period: Period; onApply: (s: Selection) => void; title?: string; showFreq?: boolean }) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(period))
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setDraft(draftOf(period))
  }

  const custom = draft.mode === 'custom'
  const error = custom ? customError(draft.start, draft.end) : null
  const days = custom ? (error ? null : daySpan(draft.start, draft.end)) : PRESETS.find((p) => p.value === draft.mode) ? resolve({ kind: 'preset', range: draft.mode as Preset, freq: 'auto' }).days : null
  const effective: Freq | null = days == null ? null : draft.freq !== 'auto' && freqAllowed(draft.freq, days) ? draft.freq : autoFreq(days)
  const preview = !error && days != null
    ? resolve(custom ? { kind: 'custom', start: draft.start, end: draft.end, freq: draft.freq } : { kind: 'preset', range: draft.mode as Preset, freq: draft.freq })
    : null

  const apply = () => {
    if (error) return
    onApply(custom
      ? { kind: 'custom', start: draft.start, end: draft.end, freq: draft.freq }
      : { kind: 'preset', range: draft.mode as Preset, freq: draft.freq })
    onClose()
  }
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }))
  const today = todayISO()
  const freqs: Array<{ value: FreqChoice; label: string }> = [
    { value: 'auto', label: 'Auto' }, { value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' },
  ]

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      title={title}
      label="Choose range and frequency"
      footer={<button type="button" className="btn btn-primary grow" disabled={!!error} onClick={apply}>Show {preview ? preview.short : 'range'}</button>}
    >
      <div className="stack range-sheet">
        <div>
          <p className="lbl">Period</p>
          <div className="segmented segmented-full range-presets" role="radiogroup" aria-label="Period">
            {[...PRESETS.map((p) => ({ value: p.value as Draft['mode'], label: p.label, aria: p.long })), { value: 'custom' as const, label: 'Custom', aria: 'Custom dates' }].map((o) => (
              <button
                key={o.value}
                type="button"
                role="radio"
                aria-checked={draft.mode === o.value}
                aria-label={o.aria}
                className={`segmented-option ${draft.mode === o.value ? 'is-active' : ''}`}
                onClick={() => set({ mode: o.value })}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>

        {custom && (
          <div className="grid-2 grid-2-even">
            <Field label="From">
              <input type="date" value={draft.start} min={addDays(today, -(MAX_DAYS * 3))} max={draft.end || today} onChange={(e) => set({ start: e.target.value })} />
            </Field>
            <Field label="To">
              <input type="date" value={draft.end} min={draft.start} max={today} onChange={(e) => set({ end: e.target.value })} />
            </Field>
          </div>
        )}
        {error && <p className="field-error" role="alert">{error}</p>}

        {showFreq && <div>
          <p className="lbl">Show values per</p>
          <div className="segmented segmented-full" role="radiogroup" aria-label="Frequency">
            {freqs.map((o) => {
              const disabled = o.value !== 'auto' && days != null && !freqAllowed(o.value, days)
              return (
                <button
                  key={o.value}
                  type="button"
                  role="radio"
                  aria-checked={draft.freq === o.value}
                  disabled={disabled}
                  className={`segmented-option ${draft.freq === o.value ? 'is-active' : ''}`}
                  onClick={() => set({ freq: o.value })}
                >
                  {o.label}
                </button>
              )
            })}
          </div>
          <p className="muted small" style={{ marginTop: 6 }}>
            {draft.freq === 'auto' && effective ? `Auto = ${FREQ_WORD[effective]} for this range. ` : ''}
            Weekly and monthly charts show averages (totals for steps, km and drinks).
          </p>
        </div>}

        {preview && (
          <p className="range-preview">
            <b>{rangeText(preview.start, preview.end)}</b> · {preview.days} days{showFreq ? `, ${FREQ_WORD[preview.freq]}` : ''}
            <span className="muted small block">Compared with {rangeText(preview.compareStart, preview.compareEnd)}</span>
          </p>
        )}
      </div>
    </BottomSheet>
  )
}
