# R17 — Recovery routine, bad-data filter, illness mode, coach memory page

Requested by Rohit 2026-10-08. Same rules as before (safety only easier; tenant
isolation; aggregates only to AI; private habit never to AI). R10 design language;
plain-language (i) on new numbers.

## 1. Recovery routine after runs
- After a run is ingested (and on demand from the run sheet), build a 5–8 min routine
  matched to the run (pure `analysis/recovery_routine.py`): base cool-down walk + stretch
  set chosen by run type/duration/intensity, hills (elevation gain), cadence/ground
  contact flags, pain reports (skip/soften stretches for painful areas; never stretch
  into pain), injury watch flags. Exercises reuse/extend the Guides figures (calf,
  hamstring, quad, hip flexor, glute/piriformis, IT band/hip, adductor, lower back,
  foam-roll variants marked optional), each with seconds/side, cue and SVG figure.
- `GET /api/activities/{id}/recovery/` → {minutes, reason, steps[{key, title, seconds,
  per_side, cue, figure, optional}]}; `POST …/recovery/done/`.
- UI: "Recovery · 6 min" card on Today for 6 h after a run + button in the run sheet →
  full-screen guided timer (figure, countdown, side switch cue, next-up, pause/skip,
  haptic/beep), done → small badge/streak hook (R10 achievements: "Recovery streak").
  Optional push "Recovery routine ready" (off by default).

## 2. Bad-data filter (HR spikes, GPS jumps)
- Pure `analysis/data_quality.py` per activity: optical-HR artefacts (cadence lock —
  HR ≈ cadence ±5 for > 60 s, sudden jumps > 25 bpm in < 5 s not matched by pace,
  flat-lined HR, HR above max), GPS glitches (implied speed > 7 m/s for runner, teleports
  > 50 m between 1 s samples, stationary drift), pauses mis-marked. Output: cleaned
  series (interpolated or masked), flags[{kind, start_s, end_s, severity}], quality
  score 0–100, and which metrics are affected.
- Use the cleaned series in all downstream analysis (segmentation, HR drift, heart
  adaptation, progress, PRs, run review, compare); recompute derived metrics on deploy
  via existing `derive`/reingest command (document). Keep raw data untouched.
- `quality` block on activity detail/route/share-data; runs with quality < 50 are
  excluded from trends by default ("Excluded from trends — wrist HR unreliable") with an
  athlete override (include/exclude toggle per run).
- UI: small "Data check" chip in the run sheet (✓ clean / ⚠ fixed 2 HR spikes / ✕ excluded)
  with a sheet explaining what was fixed + HR chart showing the masked parts greyed.

## 10. Illness mode
- "I'm sick / injured" (Today ⋯, Me, coach chat tool `set_illness`) with type (cold,
  fever/flu, stomach, injury, other), symptoms above/below neck, start date, optional
  expected days. While active: upcoming workouts are paused (status `paused`, removed
  from the watch via registry), readiness/briefing/auto-adjust/reminders switch to rest
  messaging, weekly reports note it, streaks/badges don't break.
- Return: "I'm better" → return-to-run block generated from days off + illness type
  (rule of thumb: off ≤ 3 days → 2–3 easy sessions at 50–70 % of previous duration;
  4–7 days → one easy week; > 7 days or fever → 1–2 weeks rebuild, start with run/walk),
  HR caps lower for the first sessions; then re-flow back into the plan (shift race
  date warning if the race gets too close). Fever/"below the neck" symptoms → advise no
  running until symptom-free 24–48 h (non-medical wording, "see a doctor if…").
- Health data during illness (RHR up, HRV down) is flagged so trends/habit reports
  don't treat it as normal (exclude or annotate).
- Endpoints: `GET/POST /api/illness/`, `POST /api/illness/{id}/recover/`, history.

## 16. Coach memory page
- Me → "What the coach knows": list MemoryFacts grouped (injuries & health, schedule &
  preferences, goals, other) with source (chat/check-in/app) and date; edit text, delete,
  pin (always in context), add new fact; "the coach will forget this" confirm on delete.
- Endpoints: `GET/POST /api/memory/`, `PATCH/DELETE /api/memory/{id}/`; facts are
  athlete-scoped; edits are what the chat context uses next turn; private habit never
  stored as a fact (filter + test).
