# R16 — Edit plans (app + chat), honest coach, dated day metrics

Requested by Rohit 2026-10-08.

## A. Edit a workout (and a week) in the app
- `PATCH /api/workouts/{id}/edit/` (future/today, not completed; RACE only notes) with
  any of: `total_minutes` (scale), `add_minutes` (±, applied to run or walk parts per
  `apply_to: run|walk|both`), full `steps` list (kinds: warmup, run, walk, recovery,
  cooldown, strides, other; each `duration_s`, optional `repeat` group, optional
  target `hr_low/hr_high` or `pace_low/pace_high` s/km, `note`), `notes`.
- Validation: 5–240 min total, step 10 s–90 min, HR within resting..max, pace sane.
  **User edits are allowed** but return `warnings[]` in plain words when the session
  gets much harder than planned (run time > +25 % vs plan, any HR target above the
  athlete's ceiling, 2 hard days in a row, long run > 40 % of the week). Warnings never
  block; the UI shows them before saving ("Save anyway").
- The workout is marked `edited_by: "user"` (auto-adjust, weather swaps and re-layout
  must not overwrite it; re-layout keeps its content, only date may move by rules) with
  an "Undo my edits" (restore generated version) endpoint.
- Watch: if it was on the watch, re-send automatically (registry replaces the old
  copy). Response includes `garmin_status`.
- Week tools: `POST /api/plan/week-edit/` {week_start, action: add_minutes|scale|
  add_walk_breaks|set_hr_range, value, kinds?} applying A to every matching future
  workout that week, same warnings.
- UI: workout sheet → "Edit" → step editor (list of step rows with duration
  steppers, type picker, target picker HR range / pace range / none, drag/up-down
  reorder, duplicate, delete, "+ Add walk / run / strides / warm-up / cool-down",
  repeat blocks e.g. "3 × (3 min run + 1 min walk)"), quick actions (+5 min, −5 min,
  add walk breaks, set HR range), live total time + bar preview, warnings, Save →
  "Updated on watch ✓". Plan week header → "Edit week" sheet.

## B. Coach chat can actually change workouts — and never pretends
- New chat tools: `edit_workout(id, total_minutes?, add_minutes?, apply_to?, steps?,
  hr_low?, hr_high?, notes?)` and `edit_week(week_start, action, value, kinds?)`
  calling the same services as A (same warnings, same watch re-send). Chat-requested
  increases up to +20 % per session apply directly; bigger increases → the tool returns
  `needs_confirmation` and the coach asks the athlete first (then calls again with
  `confirmed: true`).
- System prompt rule + guard: the coach must never say a plan/workout was changed
  unless a tool call in this turn succeeded; after any change it states exactly what
  changed (date, before → after). Server-side guard: if the assistant text claims a
  change ("I've updated/increased/changed/moved…") and no mutating tool succeeded in
  the turn, append a correction / re-prompt once so the reply is honest.
- Chat replies that changed the plan show a small "Plan updated" chip linking to the
  workout; the Plan/Today queries are invalidated so the change appears immediately.

## C. Dates on day metrics (not cluttered)
- Every day-scoped value in API responses carries its `date` (sleep, HRV, readiness,
  resting HR, body battery, stress, steps, weight…) and the response has `as_of`.
- UI: show the date only when it isn't "today/last night": a tiny muted suffix such as
  "· 7 Oct" or "· yesterday" on tiles/rings, and a one-line "Showing yesterday's sleep —
  your watch hasn't synced last night yet" with a Sync button on Today when today's
  sleep/readiness is missing. Fresh data shows no label (no clutter).
- Auto-sync: when the app opens (or regains focus) and the last Garmin sync is > 60
  min old and it's after 5 am local, trigger a sync (existing endpoint, respects the
  rate-limit breaker; at most once per 30 min); show a small "Syncing…" indicator and
  refresh affected queries when done.
