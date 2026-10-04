# API notes — where the backend differs from, or adds to, SPEC.md §5

Everything in §5 is implemented with the exact field names and shapes. This file lists
the places where the spec was silent or where the backend had to choose.

## Additions (extra fields or behaviour; nothing in §5 was removed)

- **Thread** (`POST/PATCH /chat/threads/…`) = `{id, title, updated_at, created_at}`.
  `GET /chat/threads/` returns exactly `{id, title, updated_at}`.
- **Plan.summary** holds the generator facts: `runway, weeks, peak_run_km,
  ideal_peak_run_km, reached_ideal_peak, peak_continuous_s, race_needs_continuous_s,
  will_run_continuously, warnings[], is_target, race_created, available_days,
  long_run_day, baseline{…}, baseline_source ("history" | "beginner_defaults")`.
- `GET /plans/?status=` also accepts a comma list (`?status=proposed,active`).
- `GET /calendar/` with no params defaults to `today-7 … today+14`.
- `POST /workouts/{id}/guide/` and `POST /activities/{id}/review/` return **201**
  `{thread_id}`. They run the first chat turn synchronously (5–30 s).
- `POST /memory/` with text that already exists (case-insensitively) returns **200** and
  the existing fact instead of creating a duplicate.

## Choices the spec left open

- **ActivityCard.name / device** — activities have no stored name. `name` is built like
  Garmin's ("Morning Run", "Evening Walk") from the start time in the athlete's
  timezone; `device` is `"Garmin"` for synced activities, `"FIT upload"` otherwise (the
  watch model is not stored).
- **ActivityCard.steps** are the run/walk segments (stops left out, as gaps). Pace and HR
  min/max are both the segment's average (min = max).
- **Calendar items**: on a day with both, activities come first, then workouts. A
  completed workout still appears alongside its activity (`status: "completed"`,
  `completed_activity_id` set), so the UI can choose to hide one. Workouts from
  `proposed` / `declined` plans never appear.
- **rest** is `"Recovery day"` when the previous day had a long / intervals / tempo /
  race workout (not skipped) or an activity of 75 min+; otherwise `"Rest"`.
- **weeks[]** are Monday–Sunday weeks overlapping the range, totalled over the *whole*
  week even when the range cuts it. Skipped workouts are excluded from `planned_*`.
- **Plans start tomorrow.** `current_phase_id` is the phase containing today, or the
  first phase if the plan has not started yet.
- **Accepting** archives the previous active plan and deletes its *planned* workouts
  dated after today (today's is kept — the athlete may be mid-session). Accepting also
  makes the plan's race the target race and copies the plan's available days / long-run
  day onto the profile.
- **Declining** deletes the proposal's workouts and the race it created (if nothing else
  uses that race).
- **Workout PATCH** refuses moving into the past (400). `moved_from` keeps the original
  date across several moves. Setting status away from `completed` clears the link.
- **Fitness**: activities that could not be segmented (cycling, strength) count their
  timer minutes at walking effort (load 1/min) rather than zero.
- **Metric entries**: `resting_hr` history also includes Garmin's nightly values from
  wellness data with `id: null, source: "garmin"` (not deletable). Only `weight` and
  `threshold_pace` mirror onto the athlete (per spec). Editing `weight_kg` or
  `threshold_pace_s` through `PATCH /athlete/` also writes a manual entry. Values outside
  plausible bounds are 400 (weight 25–300, threshold 150–1200 s/km, RHR 25–120, max HR
  120–230). No `"estimated"` entries are produced yet.
- **Diet targets** without a weight use 70 kg so the screen renders; `missing_profile`
  then contains `"weight_kg"`. Age comes from `date_of_birth`, so the missing key is
  `"date_of_birth"` (not `"age"`).
- **Diet `/diet/trend/` series** gives raw daily `intake_kcal` (null on unlogged days);
  the 7-day average is for the client to compute. `summary` is all-null except
  `logged_days_last_7` until 5 of the last 7 days are logged.
- **Fueling** for planned workouts has no time of day, so `before` gives the normal
  option *and* the early-morning one. `carbs_g_during_per_h` is the lower bound of the
  band (30 or 45).
- **Meal photo URLs** are `/api/media/meals/<athlete>/<uuid>.<ext>` — under `/api/` so the
  Vite dev proxy (which forwards only `/api`) reaches them. Served by Django in DEBUG only
  and **without auth** (random filenames). Production needs a real file server.
- **Meal create** accepts JSON as well as multipart. `items` may be a JSON string
  (multipart) or a list (JSON). Totals are always recomputed from items; client-sent
  totals are ignored. `eaten_at` defaults to now.
- **Meal estimate**: `503 {detail}` for no key, model errors and an exhausted monthly
  budget alike. Totals are summed in Python from the model's items.
- **Chat** never returns 500 on model failure: the assistant message is stored with
  `status: "error"` and readable text, response 200. Tool side effects that already
  happened (a proposal, a logged meal) keep their attachments even then.
- **Throttles**: chat POSTs, Guide/Review and meal estimates share a `chat` scope of
  150/day per user. The monthly 200-call AI budget (every model call, tool iterations
  included) is the real limit.

## Planning with no running history

A new account (no segmented runs) gets a beginner baseline: 5 km of running a week at
the athlete's own easy pace, mostly run/walk, plus a warning in `summary.warnings`. The
old 1 km/week floor produced 4-minute sessions.

## R6 (SPEC_R6.md) — additions and choices

**§1 history**
- `Plan.summary` adds `last_run_date` (ISO or null), `gap_days`, `detraining_factor`,
  `best_week: {start, run_km, longest_run_s} | null`. The detraining sentence goes into
  `summary.warnings` (first). When the detrained volume is under 5 km/week the floor
  applies and the sentence says so ("… lifted to the 5 km beginner floor").
- A "block" = runs no more than 14 days apart, newest first, within 16 weeks.
- Sync depth: an `Athlete.garmin_backfilled` flag (new). Until it is set — i.e. on the
  first sync **and once for existing accounts** — the listing pages back 12 months
  (100 per page); afterwards pages of 20 until a known id, max 100. At most 60
  downloads per sync; a capped or rate-limited backfill continues next sync.
- Chat system prompt context gains `history_summary` (`first_activity, activities, runs,
  total_hours, total_run_km, last_run_date, gap_days, best_week {week_starting, run_km},
  longest_unbroken_run {minutes, date}, run_km_by_month {YYYY-MM: km}`).

**§2 unplanned runs / adaptation**
- `unplanned: bool` is on the **ActivityCard** everywhere *and* on the calendar CalItem
  (`{type:"activity", activity, unplanned}`). True = a running activity not linked to
  any planned workout. Walks/rides are never `unplanned`.
- `Plan` (detail) gains `adjustments: [{week_start, reason, factor, created_at}]`.
  `week_start` is the Monday of the week that was **adjusted** (the one after the
  reviewed week). A row is written for every reviewed week (factor 1.0 for "follow" and
  ">130 %" too) — that row is the idempotency key. No row when the reviewed week had no
  planned workouts (e.g. the plan's first week).
- Comparison is running **minutes** (non-walk step time vs `run_duration_s` of every
  activity that week, planned or not). "Repeat" scales the coming week's future,
  not-completed, non-race workouts to last week's planned running time (never up);
  workouts are rebuilt through the normal builder, so steps stay on the grid.
- Celery: `planning.adapt_week` after each successful `ingest.sync_one`; `planning.adapt_all`
  Mondays 01:00 UTC. A mid-sync 429 now also trips the Garmin breaker.

**§3 actual vs planned**
- Workout always has `actual`, `compliance`, `review` keys — all `null` until
  `completed_activity_id` is set.
- `actual.time_in_zone` is Z1..Z5 only (seconds below Z1 dropped); null without zones.
  Extra keys in `actual`: `max_cadence_spm, avg_stride_length_m,
  avg_vertical_oscillation_cm, avg_ground_contact_ms, avg_respiration,
  training_effect_aerobic, training_effect_anaerobic`.
- `review` has an extra `generated_at` (null when `status:"none"`).
- `compliance.score` is the mean of the checks (hit 100, close 60, missed 0).
  `easy_effort` counts time **at or below** the target zone (walk breaks in Z1 are
  correct). `hr_ceiling` is skipped for intervals/tempo/race. `planned`/`actual` in each
  check are display strings ("27:00", "≥ 70 %", "152 bpm").
- `POST /workouts/{id}/review/` → **200 Workout** (with `review`), 409 if no linked
  activity, 503 `{detail}` on AIUnavailable (no key, budget, outage). Cached in
  AIAnalysis (`kind: review`) by input hash.
- `POST /activities/{id}/review/` already meant "open a chat review thread", so the
  stored AI review for an (unplanned) activity is **`POST /activities/{id}/ai-review/`**
  → 200 activity detail (below), same 503 rule.
- `GET /activities/{id}/` = the previous detail fields (`metrics`, `segments`, …) **merged
  with the ActivityCard keys** plus `actual`, `review`, `workout_id` (null if unplanned)
  and `compliance` (null if unplanned).

**§4 month calendar** (`GET /calendar/month/?month=YYYY-MM`, default current month; 400
on a bad month)
- `days` covers only the month's own dates (no Monday padding; the client offsets by the
  first date's weekday). One planned workout per day is shown (the first); skipped
  workouts are left out entirely.
- `today` is used as a status only when nothing is done yet today; a completed workout
  today is `done`/`partial`. `rest` = inside the active plan's span with nothing planned
  or run; `null` outside it. A planned WALK counts as done if any activity exists that day.
- `totals.actual_s` sums **running** activities; extra `totals.runs_extra`.

**§5 insights** (`GET /insights/?range=4w|12w|6m`, default `4w`; 400 otherwise)
- Extra top-level `range`, `today`.
- Series item shapes the spec left open: `resting_hr.series` and `stress.series` =
  `{date, value}`; `body_battery.series` = `{date, value (daily high), low}`,
  `body_battery.avg` = mean daily high; `respiration.series` = `{date, value (waking),
  sleep_value}`; `vo2max.series` = `{date, value}`; running trends = `{date, value}`
  (`longest_run_trend` value in seconds, `easy_pace_trend` value in s/km at Z2 HR).
- `running.cadence.target` = `{low: 160, high: 175}`; `cadence.trend` = spm per week.
- `race_predictions` also has `marathon_s`.
- `readiness.source:"garmin"` when today's/yesterday's row has Garmin readiness;
  `drivers` are always the computed ones (sleep, HRV vs baseline, RHR, Form). Score is
  null when no signal exists at all.
- `focus` items have an extra `key` (`breathing|recovery|sleep|consistency|easy_pace|
  cadence|run_blocks`), most urgent first, max 3.
- `summary` = `{status, markdown, generated_at}`. `POST /insights/summary/?range=` →
  that same object; returns today's stored overview without a model call unless
  `?refresh=1`. 503 `{detail}` on AIUnavailable.

**§6 Garmin**
- DailyMetrics: new `hrv_weekly_avg, hrv_baseline_low, hrv_baseline_high,
  light_sleep_seconds, respiration_sleep_avg, race_pred_5k_s/10k_s/half_s/marathon_s`.
  Existing columns kept their names instead of the spec's: `deep_sleep_seconds`,
  `rem_sleep_seconds`, `awake_seconds` (= sleep_deep_s/rem_s/awake_s) and `vo2max`
  (= Garmin's generic/running VO2max, the spec's `vo2max_running`).
  `intensity_minutes` is now moderate + 2 × vigorous (Garmin's convention).
- New call per day: `get_respiration_data`; once per sync: `get_race_predictions()`.
  Wellness fetches 28 days on the first sync, then from the last stored day to today.
  Raw payloads are merged per day; `manage.py backfill_wellness [--athlete N]` re-maps
  stored raw payloads onto new columns without calling Garmin.
- ActivityMetrics: `max_run_cadence_spm, avg_stride_length_m, avg_vertical_oscillation_cm,
  avg_ground_contact_ms, avg_respiration, training_effect_aerobic/anaerobic` (exposed via
  the activity detail `metrics` and `actual`). Training effect is read from the FIT
  session message, not the Connect summary. Watches without running dynamics get
  `avg_stride_length_m` = speed × 60 / cadence over run blocks; VO/GCT/respiration stay null.

**§7 rounding**
- Generator totals round to whole minutes; run/walk blocks, reps and recoveries to 30 s;
  warm-up/cool-down walks to whole minutes. Labels are clock format ("Run 3:30",
  "Rep 2/5 · 2:30 hard"); titles whole minutes. Strides are now 4 × 30 s (was 20 s) so
  every step is on the 30 s grid. Activity step labels are "Run 3:42" (to the second).
  Grouping "3 × (Run 3:30 · Walk 3:00)" is left to the client.

## R7 (SPEC_R7.md) — additions and choices

**§1 morning check-in** (`GET /today/`, `POST /today/apply/`, `POST /today/explain/`)
- Extra top-level key **`note`**: a recovery line for `no_plan` ("… an easy 20-min walk …")
  and `rest`; null otherwise. `headline` for `no_plan` is **"No session today"**.
- `reasons[].signal` has one value the spec's list lacks: **`"rpe"`** (yesterday's post-run
  RPE; ≥ 8 = watch). `"load"` is the ACWR. `"stress"` is never emitted (the spec gives no
  rule for it). Reasons are ordered bad → watch → good; pain/illness come first.
- `reasons[].value` is a number: sleep in **hours** (2 dp), HRV ms, RHR bpm, body battery,
  readiness, ACWR (2 dp), RPE; `true` for pain/illness. `baseline`: HRV = Garmin
  `baseline_low` (or the 28-day mean, see below), RHR = 28-day mean (1 dp), load = 1.0,
  else null. `label` is display text ("Sleep 6h 10m", "HRV 42 ms", "Resting HR 58 bpm").
- `signals_missing` ⊆ `sleep, hrv, rhr, body_battery, readiness, load`. A value with no
  baseline counts as missing: RHR needs ≥ 7 earlier nights; HRV with no Garmin baseline
  band and < 7 nights of history; ACWR (`load`) until the athlete has ≥ 21 days of
  activity history (a first week always "spikes"). No run yesterday is not "missing".
- HRV with history but no Garmin `baseline_low` yet: ≥ 12 % under the 28-day mean = watch
  (never bad — the spec's bad rule needs Garmin's band).
- "Mildly flagged" swap = exactly 2 bad and 0 watch → 50 % run/walk (every block halved
  on the 30 s grid, all easy). Otherwise swap = brisk walk of the planned minutes
  clamped to 20–30. A WALK workout is not swapped (`adjusted: null`).
- `easy`: same duration; moderate/hard steps become easy (interval/stride → run, easy
  pace and HR band, label "Easy m:ss"); every HR cap −5 bpm; INTERVALS/TEMPO become
  kind `EASY`, title "Nm easy run", target_zone Z2. `rest`: `adjusted` =
  `{kind:"REST", title:"Rest day", duration_s:0, steps:[], load:0}`.
- A **RACE** is never rewritten (`adjusted: null`, verdict and reasons still shown).
- `adjusted` = `{title, kind, duration_s, load, steps, target_zone, description}`.
- `workout` is the stored Workout. Once applied its `steps`/`title`/`kind` are the
  adjusted ones; the as-planned prescription is in the new Workout keys
  `original_steps` and `original` (`{title, kind, duration_s, load, target_zone,
  description}`). The check-in always judges the original, so applying twice does not
  ease twice; re-applying after a worse verdict starts again from the original.
- Today's workout = active plan, today, not skipped. Skipped → `no_plan`.
- `POST /today/apply/` → 409 `{detail}` when `adjusted` is null (go / no_plan / race)
  or today's workout is already completed. Returns the /today/ body.
- `POST /today/explain/` → the /today/ body with `explanation.status: "ready"`. Lite tier
  (`checkin_explain`), stored in AIAnalysis `kind: "checkin"`, keyed by a hash of
  {date, verdict, signals, planned title, adjusted title} — so "per day", and a changed
  verdict gets a fresh line. Budget-checked; 503 `{detail}` on AIUnavailable. GET never
  calls the model. Throttle scope `chat`.
- Celery: `planning.morning_checkins` hourly at :05 UTC picks athletes with an active plan
  whose local hour is 07, queues `ingest.sync_wellness_one` (garmin queue, wellness for 2
  days, breaker applies) linked to `planning.compute_checkin` (computes and returns the
  verdict; never applies; GET /today/ recomputes on read anyway).
- `WellnessSnapshot` gained optional `hrv_baseline_low, body_battery_high, acwr,
  last_rpe` (filled by `snapshot_for`; `assess` ignores them).

**§2 post-run check-in**
- `POST /activities/{id}/checkin/` → **201** JournalEntry on create, **200** when it
  replaces the activity's existing check-in (one run_log entry per activity). Only `rpe`
  is required; `legs`, `breathing`, `pain`, `note` may be omitted/null. 400 `{detail}`
  on bad values (rpe must be an integer 1–10; pain `{where (≤40 chars), level 1–10}`).
- Entry: `text` = "Post-run check-in: RPE 6/10 · legs heavy · …" (+ note), `extracted` =
  `{checkin: true, skipped: false, rpe, legs, breathing, pain, note}`, `rpe`,
  `pain_reported = bool(pain)`, `applies_to_date` = the activity's date. JournalEntry JSON
  gains `activity` (id).
- Non-empty note → `coaching.extract_checkin_note` (ai queue, after commit). It stores
  `extracted.note_facts` and can only ADD pain/illness; it never changes `rpe`.
- `POST /activities/{id}/checkin/skip/ {reason}` — no prior skip semantics existed, so:
  creates a run_log entry `{checkin: false, skipped: true, reason}` (no rpe, no pain)
  which removes the activity from pending; repeat → 200 with the existing entry.
- `GET /checkins/pending/` → newest first; sports containing "run" or "walk"; last 7 days
  including today.
- **Changed rule** (also ActivityCard.`journalled`): a date is covered only by journal
  entries **not tied to an activity** (chat notes). A check-in for one run no longer
  marks a second run the same day as journalled.
- `GET /activities/{id}/` gains `checkin` (the JournalEntry or null).
- Compliance gains an **`effort`** check for EASY/RUN_WALK/LONG/WALK when a check-in RPE
  exists: ≤ 5 hit, 6 close, ≥ 7 missed ("Felt harder than an easy run should.").

**§3 guard + Garmin**
- Workout JSON new keys: `guard` (`{hr_max, pace_min_s, pace_max_s, cadence_target}` for
  EASY/LONG/RUN_WALK, else null; cadence_target is 160 = low edge of the Insights
  cadence target), `adjusted_by` ("checkin" | null), `original_steps`, `original`,
  `garmin_workout_id`, `garmin_synced_at`, **`garmin_status`** (`"none" | "synced" |
  "changed"` — changed = steps/title/date differ from what was uploaded → "Update on
  watch").
- `actual` gains `time_above_cap_s`, **`time_above_cap_pct`** (integer %, of the time
  with HR recorded) and `hr_cap` (bpm used) — runs only, null without HR samples. Cap =
  Z2 top, else `athlete.hr_ceiling`.
- `POST /workouts/{id}/garmin/` → 200 Workout JSON + **`garmin_result`**
  `{workout_id, date, status, garmin_workout_id, synced_at, detail}` with status
  `uploaded | updated | unchanged | removed | skipped | error`. 409 `{detail, result}`
  for a past / completed / skipped workout or one with nothing to send; 502 `{detail,
  result}` when Garmin refused it; 503 `{detail}` when the job cannot run (breaker open,
  no/expired Garmin session, the garmin queue busy > 90 s).
- `DELETE /workouts/{id}/garmin/` → 200 Workout JSON + `garmin_result` (`removed`, or
  `skipped` "Not on the watch").
- `POST /plans/active/garmin/ {days}` (default 7, 1–28, today included, planned workouts
  only) → `{results: [garmin_result…], detail}`; **200** if every workout succeeded,
  **502** with the same body if any failed, 503 `{detail}` as above, 404 without an active
  plan. A 429 trips the breaker, stops the batch and marks the rest
  "Not attempted: Garmin rate limit.".
- The push runs as `planning.garmin_push` on the **garmin** queue; the request waits for it.
- Idempotency: stored `garmin_payload_hash` = sha256(exact payload JSON + date).
  Same → `unchanged` (no Garmin call). Different → unschedule + delete the old Garmin
  workout, upload, schedule. A rest-applied workout (no steps) that is on the watch is
  removed. If scheduling fails after upload, the uploaded workout is deleted again.
  New columns: `garmin_workout_id, garmin_schedule_id, garmin_synced_at,
  garmin_payload_hash` (+ `adjusted_by, original_steps, original` for §1).

**Garmin payload** (`planning/garmin_workout.py`, checked against the installed
garminconnect 0.3.10: `RunningWorkout.model_validate(payload).to_dict() == payload`).
Uploaded with `Garmin.upload_running_workout(RunningWorkout)` (→ `upload_workout` →
POST /workout-service/workout), then `schedule_workout(workoutId, "YYYY-MM-DD")`;
removal is `unschedule_workout(scheduleId)` + `delete_workout(workoutId)`.
```
{workoutName: title[:60], description?, author: {}, estimatedDurationInSecs,
 sportType: {sportTypeId: 1, sportTypeKey: "running", displayOrder: 1},
 workoutSegments: [{segmentOrder: 1, sportType: <running>, workoutSteps: [
   {type: "ExecutableStepDTO", stepOrder, stepType: {stepTypeId, stepTypeKey, displayOrder},
    endCondition: {conditionTypeId: 2, conditionTypeKey: "time", displayOrder: 2,
                   displayable: true},
    endConditionValue: seconds (float),
    targetType: {workoutTargetTypeId: 4, workoutTargetTypeKey: "heart.rate.zone",
                 displayOrder: 4}, targetValueOne: hr_min, targetValueTwo: hr_max,
    # or targetType no.target (id 1) with no values — walks and steps without a band
    description: step label, childStepId?: (inside a repeat)},
   {type: "RepeatGroupDTO", stepOrder, stepType: {6, "repeat", 6}, childStepId,
    numberOfIterations: n, smartRepeat: false, endConditionValue: n,
    endCondition: {conditionTypeId: 7, conditionTypeKey: "iterations", displayOrder: 7,
                   displayable: false},
    workoutSteps: [...]}]}]}
```
Step types: warmup→warmup(1), cooldown→cooldown(2), run/interval/stride→interval(3),
walk/recovery→recovery(4). Repeats: consecutive identical blocks (kind, duration,
intensity, HR band — labels ignored), pattern length 1–4, ≥ 2 iterations, greedy from
the left (e.g. run/walk ×3 + a final run). The custom-bpm HR target (type 4 with
targetValueOne/Two and no zoneNumber) is Garmin's documented-by-usage format; it has
not been exercised against the live API — the first real upload (Rohit, from the UI) is
the test.
