import { useMemo, useState } from 'react'
import { errorText } from '../../lib/queries'
import { useEditModel, useEditWorkout, useUndoEdit, type EditModel, type EditResponse, type EditWarning } from '../../lib/r16edit'
import { BottomSheet } from '../BottomSheet'
import { ChevronDown, PlusIcon, TrashIcon, UndoIcon } from '../Icons'
import { ErrorState, Skeleton } from '../States'
import { WorkoutBar } from '../WorkoutBar'
import {
  KINDS, addMinutes, addWalkBreaks, cloneBlock, cloneStep, fromItems, hasRunStep, insertNew, kindLabel, mmss, move,
  newRepeat, newStep, repeatText, runSeconds, setRunHr, signature, stepCount, toApi, toFlat, totalSeconds, uid,
  type Block, type EStep,
} from './editModel'
import { DurationStepper, NumStepper } from './Steppers'
import { HrRange, TargetPicker, targetText, useHrBounds, type HrBounds } from './Targets'
import '../../styles/r16edit.css'

type Props = {
  workoutId: number
  open: boolean
  onClose: () => void
  onSaved: (result: EditResponse, how: 'saved' | 'restored') => void
}

const SWATCH: Record<string, string> = {
  warmup: 'walk', run: 'easy', walk: 'walk', recovery: 'walk', cooldown: 'walk', strides: 'hard', other: 'easy',
}

/**
 * R16 §A: the step editor (lazy chunk, opened from the workout sheet's "Edit"). Reads
 * GET /workouts/{id}/edit/ (steps already folded into repeat groups), edits locally with
 * a live total + bar, checks with `dry_run` and shows warnings before saving.
 */
export default function WorkoutEditor({ workoutId, open, onClose, onSaved }: Props) {
  const model = useEditModel(workoutId, open)
  return (
    <BottomSheet open={open} onClose={onClose} title="Edit workout" full label="Edit workout">
      {model.isPending && <div className="ed"><Skeleton height={90} /><Skeleton lines={4} /></div>}
      {model.isError && <ErrorState message={errorText(model.error, 'The editor did not load.')} onRetry={() => model.refetch()} />}
      {model.data && !model.data.editable && (
        <div className="ed">
          <p className="notice">{model.data.reason || 'This workout can’t be edited any more.'}</p>
        </div>
      )}
      {model.data?.editable && (
        <Editor key={model.dataUpdatedAt} model={model.data} onClose={onClose} onSaved={onSaved} />
      )}
    </BottomSheet>
  )
}

function Editor({ model, onClose, onSaved }: { model: EditModel; onClose: () => void; onSaved: Props['onSaved'] }) {
  const bounds = useHrBounds(model)
  const L = model.limits
  const notesOnly = model.notes_only
  const initial = useMemo(() => fromItems(model.steps), [model.steps])
  const [blocks, setBlocks] = useState<Block[]>(initial)
  const [notes, setNotes] = useState(model.notes ?? '')
  const [openUid, setOpenUid] = useState<string | null>(null)
  const [panel, setPanel] = useState<null | 'walk' | 'hr'>(null)
  const [walk, setWalk] = useState({ run: 240, walk: 60 })
  const [hr, setHr] = useState<[number, number]>(bounds.easy)
  const [warnings, setWarnings] = useState<EditWarning[] | null>(null)
  const [confirmUndo, setConfirmUndo] = useState(false)
  const edit = useEditWorkout(model.workout_id)
  const undo = useUndoEdit(model.workout_id)

  const original = useMemo(() => signature(initial), [initial])
  const stepsChanged = !notesOnly && signature(blocks) !== original
  const notesChanged = notes !== (model.notes ?? '')
  const dirty = stepsChanged || notesChanged
  const total = totalSeconds(blocks)
  const was = model.planned?.duration_s ?? model.total_s
  const diff = total - was
  const flat = useMemo(() => toFlat(blocks, bounds.ceiling), [blocks, bounds.ceiling])
  const tooShort = total < L.total_min_s
  const tooLong = total > L.total_max_s
  const tooMany = stepCount(blocks) > L.max_steps
  const invalid = !notesOnly && (tooShort || tooLong || tooMany || !blocks.length)

  const change = (next: Block[]) => { setBlocks(next); setWarnings(null); edit.reset() }
  const setBlock = (u: string, f: (b: Block) => Block) => change(blocks.map((b) => (b.uid === u ? f(b) : b)))
  const setStep = (s: EStep) =>
    change(blocks.map((b) => (b.type === 'step' ? (b.step.uid === s.uid ? { ...b, step: s } : b) : { ...b, steps: b.steps.map((x) => (x.uid === s.uid ? s : x)) })))

  const add = (kind: Parameters<typeof newStep>[0] | 'repeat') => {
    const block: Block = kind === 'repeat' ? newRepeat() : { uid: uid(), type: 'step', step: newStep(kind) }
    change(insertNew(blocks, block))
    setOpenUid(block.type === 'step' ? block.step.uid : block.uid)
  }

  const body = () => ({ ...(stepsChanged ? { steps: toApi(blocks) } : {}), ...(notesChanged ? { notes } : {}) })

  const save = async (anyway: boolean) => {
    try {
      if (!anyway && stepsChanged) {
        const check = await edit.mutateAsync({ ...body(), dry_run: true })
        if (check.warnings?.length) {
          setWarnings(check.warnings)
          return
        }
      }
      onSaved(await edit.mutateAsync(body()), 'saved')
    } catch {
      /* shown under the form */
    }
  }

  const doUndo = () => undo.mutate(undefined, { onSuccess: (r) => { setConfirmUndo(false); onSaved(r, 'restored') } })

  const footer = warnings ? (
    <div className="ed-foot" role="group" aria-label="Save">
      <button type="button" className="btn btn-secondary" onClick={() => setWarnings(null)}>Keep editing</button>
      <button type="button" className="btn btn-primary btn-grow" disabled={edit.isPending} onClick={() => save(true)}>
        {edit.isPending ? 'Saving…' : 'Save anyway'}
      </button>
    </div>
  ) : (
    <div className="ed-foot" role="group" aria-label="Save">
      <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
      <button type="button" className="btn btn-primary btn-grow" disabled={!dirty || edit.isPending || invalid} onClick={() => save(false)}>
        {edit.isPending ? 'Saving…' : 'Save'}
      </button>
    </div>
  )
  return (
    <div className="ed">
      <div className="ed-summary" aria-live="polite">
        <div className="ed-total">
          <span className="lbl">Total</span>
          <span className={`ed-total-value ${tooShort || tooLong ? 'is-bad' : ''}`}>{mmss(total)}</span>
          {diff !== 0 && (
            <span className={`ed-diff ${diff > 0 ? 'is-up' : 'is-down'}`}>
              {diff > 0 ? '+' : '−'}{mmss(Math.abs(diff))} vs {model.planned ? 'plan' : mmss(was)}
            </span>
          )}
          <span className="ed-run">Running {mmss(runSeconds(blocks))}</span>
        </div>
        <WorkoutBar steps={flat} height={44} />
        {tooShort && <p className="ed-hint is-bad">A session needs at least {Math.round(L.total_min_s / 60)} minutes.</p>}
        {tooLong && <p className="ed-hint is-bad">That’s over {Math.round(L.total_max_s / 3600)} hours — the most a session can be.</p>}
        {tooMany && <p className="ed-hint is-bad">Too many steps for the watch (max {L.max_steps}).</p>}
      </div>

      {notesOnly ? (
        <p className="notice">Race day steps stay as planned. You can add a note for the day.</p>
      ) : (
        <>
          <div className="ed-quick" role="group" aria-label="Quick changes">
            <button type="button" className="ed-qbtn" onClick={() => change(addMinutes(blocks, 5))} disabled={total + 300 > L.total_max_s}>+5 min</button>
            <button type="button" className="ed-qbtn" onClick={() => change(addMinutes(blocks, -5))} disabled={total - 300 < L.total_min_s}>−5 min</button>
            <button type="button" className={`ed-qbtn ${panel === 'walk' ? 'is-on' : ''}`} aria-expanded={panel === 'walk'} onClick={() => setPanel(panel === 'walk' ? null : 'walk')} disabled={!hasRunStep(blocks)}>Walk breaks</button>
            <button type="button" className={`ed-qbtn ${panel === 'hr' ? 'is-on' : ''}`} aria-expanded={panel === 'hr'} onClick={() => setPanel(panel === 'hr' ? null : 'hr')} disabled={!hasRunStep(blocks)}>HR for runs</button>
          </div>

          {panel === 'walk' && (
            <div className="ed-panel">
              <p className="ed-panel-title">Break each run into run / walk</p>
              <div className="ed-range-row"><span className="ed-range-lbl">Run</span><DurationStepper label="Run part" value={walk.run} min={30} max={20 * 60} onChange={(v) => setWalk({ ...walk, run: v })} /></div>
              <div className="ed-range-row"><span className="ed-range-lbl">Walk</span><DurationStepper label="Walk part" value={walk.walk} min={15} max={5 * 60} onChange={(v) => setWalk({ ...walk, walk: v })} /></div>
              <div className="ed-panel-actions">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPanel(null)}>Cancel</button>
                <button type="button" className="btn btn-primary btn-sm" onClick={() => { change(addWalkBreaks(blocks, walk.run, walk.walk)); setPanel(null) }}>Add walk breaks</button>
              </div>
            </div>
          )}
          {panel === 'hr' && (
            <div className="ed-panel">
              <p className="ed-panel-title">Same heart-rate range on every run step</p>
              <HrRange low={hr[0]} high={hr[1]} bounds={bounds} onChange={(l, h) => setHr([l, h])} />
              <div className="ed-panel-actions">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPanel(null)}>Cancel</button>
                <button type="button" className="btn btn-primary btn-sm" onClick={() => { change(setRunHr(blocks, hr[0], hr[1])); setPanel(null) }}>Set for all runs</button>
              </div>
            </div>
          )}

          <ol className="ed-list">
            {blocks.map((b, i) => {
              const actions: RowActions = {
                up: i > 0 ? () => change(move(blocks, i, -1)) : undefined,
                down: i < blocks.length - 1 ? () => change(move(blocks, i, 1)) : undefined,
                duplicate: () => change([...blocks.slice(0, i + 1), cloneBlock(b), ...blocks.slice(i + 1)]),
                remove: () => change(blocks.filter((x) => x.uid !== b.uid)),
              }
              return (
                <li key={b.uid} className={`ed-block ${b.type === 'repeat' ? 'is-repeat' : ''}`}>
                  {b.type === 'step' ? (
                    <StepRow
                      step={b.step}
                      open={openUid === b.step.uid}
                      onToggle={() => setOpenUid(openUid === b.step.uid ? null : b.step.uid)}
                      onChange={setStep}
                      bounds={bounds}
                      limits={L}
                      actions={actions}
                    />
                  ) : (
                    <RepeatBlock
                      block={b}
                      openUid={openUid}
                      setOpenUid={setOpenUid}
                      bounds={bounds}
                      limits={L}
                      onChange={(nb) => setBlock(b.uid, () => nb)}
                      actions={{
                        ...actions,
                        ungroup: () => change([
                          ...blocks.slice(0, i),
                          ...Array.from({ length: b.count }, () => b.steps.map((s): Block => ({ uid: uid(), type: 'step', step: cloneStep(s) }))).flat(),
                          ...blocks.slice(i + 1),
                        ]),
                      }}
                    />
                  )}
                </li>
              )
            })}
          </ol>
          {!blocks.length && <p className="muted small centered-text">No steps yet — add one below.</p>}

          <div className="ed-add" role="group" aria-label="Add a step">
            {([['walk', 'Walk'], ['run', 'Run'], ['strides', 'Strides'], ['warmup', 'Warm-up'], ['cooldown', 'Cool-down'], ['repeat', 'Repeat']] as const).map(([k, label]) => (
              <button key={k} type="button" className="ed-addbtn" onClick={() => add(k)}>
                <PlusIcon size={16} /> {label}
              </button>
            ))}
          </div>
        </>
      )}

      <label className="field">
        <span className="field-label">Your note for this day</span>
        <textarea className="ed-notes" rows={2} maxLength={1000} value={notes} onChange={(e) => { setNotes(e.target.value); setWarnings(null) }} placeholder="e.g. Hilly route, keep it relaxed" />
      </label>

      {model.edited_by === 'user' && (
        confirmUndo ? (
          <div className="ed-panel">
            <p className="ed-panel-title">Go back to the coach’s version?</p>
            <p className="muted small">Your changes to this workout are replaced by the plan’s own version{model.planned ? ` (${model.planned.title})` : ''}. If it’s on your watch, the watch copy is updated too.</p>
            <div className="ed-panel-actions">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmUndo(false)}>Keep mine</button>
              <button type="button" className="btn btn-danger btn-sm" disabled={undo.isPending} onClick={doUndo}>{undo.isPending ? 'Restoring…' : 'Undo my edits'}</button>
            </div>
            {undo.isError && <p className="bad small">{errorText(undo.error, 'Could not restore the plan version.')}</p>}
          </div>
        ) : (
          <button type="button" className="btn btn-ghost ed-undo-btn" onClick={() => setConfirmUndo(true)}>
            <UndoIcon size={18} /> Undo my edits
          </button>
        )
      )}

      <div className="ed-sticky">
        {warnings && (
          <div className="ed-warnings" role="alert">
            <p className="ed-warnings-title">Harder than planned</p>
            <ul>{warnings.map((w, i) => <li key={`${w.key}-${i}`}>{w.text}</li>)}</ul>
            <p className="ed-warnings-sub">You can still save it — it’s your call.</p>
          </div>
        )}
        {edit.isError && <p className="bad small">{errorText(edit.error, 'Could not save the workout.')}</p>}
        {footer}
      </div>
    </div>
  )
}

type RowActions = { up?: () => void; down?: () => void; duplicate: () => void; remove: () => void; ungroup?: () => void }

function RowTools({ actions, what }: { actions: RowActions; what: string }) {
  return (
    <div className="ed-tools" role="group" aria-label={`${what}: move, copy, delete`}>
      <button type="button" className="ed-tool" onClick={actions.up} disabled={!actions.up} aria-label={`Move ${what} up`}><ChevronDown size={18} className="flip" /></button>
      <button type="button" className="ed-tool" onClick={actions.down} disabled={!actions.down} aria-label={`Move ${what} down`}><ChevronDown size={18} /></button>
      <button type="button" className="ed-tool ed-tool-text" onClick={actions.duplicate}>Duplicate</button>
      {actions.ungroup && <button type="button" className="ed-tool ed-tool-text" onClick={actions.ungroup}>Ungroup</button>}
      <button type="button" className="ed-tool is-bad" onClick={actions.remove} aria-label={`Delete ${what}`}><TrashIcon size={18} /></button>
    </div>
  )
}

type Limits = EditModel['limits']

function StepRow({
  step, open, onToggle, onChange, bounds, limits, actions, inGroup = false,
}: {
  step: EStep
  open: boolean
  onToggle: () => void
  onChange: (s: EStep) => void
  bounds: HrBounds
  limits: Limits
  actions: RowActions
  inGroup?: boolean
}) {
  const name = kindLabel(step.kind)
  const target = targetText(step.target)
  return (
    <div className={`ed-step ${open ? 'is-open' : ''} ${inGroup ? 'in-group' : ''}`}>
      <button type="button" className="ed-step-head" aria-expanded={open} onClick={onToggle}>
        <span className={`ed-swatch wbar-${SWATCH[step.kind]}`} aria-hidden="true" />
        <span className="ed-step-main">
          <span className="ed-step-name">{name}</span>
          {(target || step.note) && <span className="ed-step-sub">{[target, step.note].filter(Boolean).join(' · ')}</span>}
        </span>
        <span className="ed-step-dur">{mmss(step.duration_s)}</span>
        <ChevronDown size={18} className={`ed-chev ${open ? 'flip' : ''}`} />
      </button>
      {open && (
        <div className="ed-step-body">
          <div className="ed-kinds" role="radiogroup" aria-label="Step type">
            {KINDS.map((k) => (
              <button
                key={k.kind}
                type="button"
                role="radio"
                aria-checked={step.kind === k.kind}
                className={`ed-kind ${step.kind === k.kind ? 'is-on' : ''}`}
                onClick={() => onChange({ ...step, kind: k.kind, intensity: undefined })}
              >
                {k.label}
              </button>
            ))}
          </div>
          <DurationStepper label={`${name} duration`} value={step.duration_s} min={limits.step_min_s} max={limits.step_max_s} onChange={(v) => onChange({ ...step, duration_s: v })} />
          <TargetPicker target={step.target} bounds={bounds} onChange={(t) => onChange({ ...step, target: t })} />
          <input className="ed-note" type="text" maxLength={80} value={step.note} placeholder="Step note (optional)" aria-label="Step note" onChange={(e) => onChange({ ...step, note: e.target.value })} />
          <RowTools actions={actions} what={name} />
        </div>
      )}
    </div>
  )
}

function RepeatBlock({
  block, openUid, setOpenUid, bounds, limits, onChange, actions,
}: {
  block: Extract<Block, { type: 'repeat' }>
  openUid: string | null
  setOpenUid: (u: string | null) => void
  bounds: HrBounds
  limits: Limits
  onChange: (b: Block) => void
  actions: RowActions
}) {
  const open = openUid === block.uid
  const per = block.steps.reduce((t, s) => t + s.duration_s, 0)
  return (
    <div className="ed-rep">
      <div className="ed-rep-head">
        <NumStepper label="Repeats" value={block.count} min={1} max={limits.repeat_max} format={(v) => `${v} ×`} onChange={(count) => onChange({ ...block, count })} />
        <button type="button" className="ed-rep-sum" aria-expanded={open} aria-label={`${repeatText(block)}: group options`} onClick={() => setOpenUid(open ? null : block.uid)}>
          <span className="ed-rep-text">{repeatText(block, false)}</span>
          <span className="ed-step-dur">{mmss(per * block.count)}</span>
        </button>
      </div>
      <ol className="ed-rep-steps">
        {block.steps.map((s, j) => (
          <li key={s.uid}>
            <StepRow
              step={s}
              inGroup
              open={openUid === s.uid}
              onToggle={() => setOpenUid(openUid === s.uid ? null : s.uid)}
              onChange={(ns) => onChange({ ...block, steps: block.steps.map((x) => (x.uid === ns.uid ? ns : x)) })}
              bounds={bounds}
              limits={limits}
              actions={{
                up: j > 0 ? () => onChange({ ...block, steps: move(block.steps, j, -1) }) : undefined,
                down: j < block.steps.length - 1 ? () => onChange({ ...block, steps: move(block.steps, j, 1) }) : undefined,
                duplicate: () => onChange({ ...block, steps: [...block.steps.slice(0, j + 1), cloneStep(s), ...block.steps.slice(j + 1)] }),
                remove: () => block.steps.length > 1 ? onChange({ ...block, steps: block.steps.filter((x) => x.uid !== s.uid) }) : actions.remove(),
              }}
            />
          </li>
        ))}
      </ol>
      {open && (
        <div className="ed-rep-body">
          <div className="ed-add ed-add-in" role="group" aria-label="Add to this group">
            {block.steps.length < 10 && (['run', 'walk', 'recovery', 'strides'] as const).map((k) => (
              <button key={k} type="button" className="ed-addbtn" onClick={() => onChange({ ...block, steps: [...block.steps, newStep(k)] })}>
                <PlusIcon size={16} /> {kindLabel(k)}
              </button>
            ))}
          </div>
          <RowTools actions={actions} what="group" />
        </div>
      )}
    </div>
  )
}
