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
- **Meal photo URLs** are signed and expire after 1 h:
  `/api/media/signed/meals/<athlete>/<uuid>.<ext>?exp=<unix>&sig=<hmac>` (no auth header,
  so they work in `<img src>`). Tampered, expired or traversing paths → 404. Clients must
  not cache `photo_url` past the hour; refetch the meal. Raw `/api/media/` is DEBUG-only.
- **Meal create** accepts JSON as well as multipart. `items` may be a JSON string
  (multipart) or a list (JSON). Totals are always recomputed from items; client-sent
  totals are ignored. `eaten_at` defaults to now.
- **Meal estimate**: `503 {detail}` for no key, model errors and an exhausted monthly
  budget alike. Totals are summed in Python from the model's items.
- **Chat** never returns 500 on model failure: the assistant message is stored with
  `status: "error"` and readable text, response 200. Tool side effects that already
  happened (a proposal, a logged meal) keep their attachments even then.
- **Throttles** (all 429 `{detail}`): login 10/min, register 5/hour, refresh 60/min,
  Garmin connect 5/hour — per client IP (`CF-Connecting-IP` when
  `TRUST_CF_CONNECTING_IP=1`; `X-Forwarded-For` is ignored). Chat POSTs, Guide/Review and
  meal estimates share a `chat` scope of 150/day per user (this scope was inert on
  function views until 2026-10-04). The monthly 200-call AI budget (every model call, tool iterations
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
- One RunCoach copy per day (`apps/planning/garmin_registry.py`): every Garmin workout
  the app uploads (running and strength) is recorded in **`GarminUpload`** (athlete,
  garmin_workout_id, schedule id, date, source, row FK SET_NULL; migration 0007
  backfills it from rows that already hold a Garmin id). Every send — including an
  `unchanged` one, a rest-day send and a week send — first sweeps the workout's date
  (and the date its old copy is on, when it moved) and unschedules + deletes every
  registered copy no current PlannedWorkout/StrengthSession holds any more (left over
  by plan rebuilds, re-layouts, swaps, row reuse, or a forget that hit the breaker).
  Identification is by stored id only, never by name: workouts the athlete made in
  Garmin Connect are never registered, so never touched. Copies already gone (404) are
  dropped from the registry; a 429 trips the breaker and keeps the row for next time.

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
    # every step has an HR target (the watch shows its target screen throughout):
    #   banded run steps: their band, unchanged;
    #   walk-intensity steps (walk, walk warm-up/cool-down/recovery): gentle band
    #     low = max(resting_hr + 20, 90), high = hr_easy_max (else hr_ceiling) lowered
    #     to the lowest run-step top in the workout; at least 10 bpm wide;
    #   unbanded non-walk steps (strides/reps without zones): easy → (hr_easy_min,
    #     hr_easy_max), else (hr_easy_max, hr_ceiling).
    # no.target (id 1) only when there is nothing to derive a band from. Strength
    # workouts (planning/garmin_strength.py) stay no.target.
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

## Plan re-flow (2026-10-07)

- `PATCH /api/athlete/` that changes `available_days` or `long_run_day` moves the ACTIVE
  plan's future workouts onto the new days in the same transaction — no regeneration;
  title, steps, volume, load, adaptations and check-in changes are kept, only `date`
  (and `phase`, re-derived from the phase ranges) change. Every PATCH/PUT response has
  **`plan_reflow`**: `{moved, dropped, watch_updated, watch_removed}`, or `null` when
  nothing changed (no active plan, days unchanged, or the plan already fits).
- Rules (`planning/reflow.py`, pure): per ISO week; only `planned`, non-RACE workouts
  after today and before the race move. A week whose runs already sit on available
  days, within the run-day limit, with the long run on the long-run day, is left as is
  (so adding a day moves nothing and re-flowing is idempotent). Otherwise runs go on
  `run_days(available, long_day, n)` (the generator's spread), LONG on the long-run day
  (else the last free day), INTERVALS/TEMPO away from each other and the long run where
  possible, the rest in original order. The limit is the generator's
  (`run_day_limit`: 4 while the plan's stored `summary.baseline.run_km_per_week` < 15,
  else 5; 5 if no baseline is stored) minus fixed runs already in that week (today's,
  completed ones). Too many runs: the shortest EASY/RUN_WALK are **deleted** (never
  LONG, hard or RACE; nothing is lengthened); undroppable runs that still do not fit
  stay on a free day of their week. WALKs fill free days or are deleted.
- `moved_from` keeps the ORIGINAL date (as for manual moves) and is cleared when a
  workout lands back on it. A record `{moved, dropped, watch_updated, watch_removed,
  reason: "training days changed", at, available_days, long_run_day}` is appended to
  `plan.summary.reflows` (last 20); `summary.available_days/long_run_day` follow the
  profile. `PlanAdjustment` is not used — its (plan, week_start) row is the weekly
  adaptation's idempotency key.
- `POST /plans/active/rebuild/` still exists; the Settings UI no longer offers it.

**Watch follows every change** (`apps/planning/garmin_sync.py`). For workouts already
on Garmin (`garmin_workout_id` set) — never others — after commit: re-flow move,
`PATCH /workouts/{id}/` date change, chat `move_workout`, `POST /today/apply/` → the
`planning.garmin_push` "send" job (unschedule + delete the old copy, upload + schedule
on the current date; the payload hash already included the date). Re-flow drop →
`planning.garmin_forget`. `PATCH` status `skipped`, chat `skip_workout` / `clear_day` →
"delete" job. Queued only when `garmin_status` is `changed`. The breaker is honoured
(no calls; the workout stays `changed` → "Update on watch"); `garmin_forget` re-queues
itself every 30 min (max 6 tries) while the breaker is open. A broker failure is logged
and never fails the save.

## Auth additions (docs/DEPLOY.md §2, 2026-10-04)

- `GET /api/auth/registration/` → `{mode}`: `open` · `invite` · `closed`. Public.
- `POST /api/auth/register/` takes `invite_code` (case-insensitive). `invite` mode: missing,
  unknown, used-up or expired → 400 `{invite_code: [...]}`; a failed registration does not
  use the code. `closed` → 403 `{detail}`.
- `DELETE /api/auth/me/ {password}` → 204 and clears the refresh cookie; wrong password →
  400 `{detail}`. Deletes the user, every row, FIT files, meal photos and the Garmin token
  directory, and blacklists all refresh tokens. Throttled like login.
- `GET /api/health/live/` → `{status: "ok"}`, no dependencies (liveness). `/api/health/`
  (db + Redis) is readiness. Both answer regardless of the Host header.
- `InviteCode` lives in admin: "Generate code" on the list page, or the action
  "Generate a new code like each selected one".

## R8 (SPEC_R8.md) — additions and choices

**§A runs per week**
- Athlete JSON: `runs_per_week` (null | 2–6, writable; 1/7/non-int → 400),
  `runs_per_week_recommended` (= `run_day_limit` on the active plan's
  `summary.baseline.run_km_per_week`, else the history baseline, else the 5 km/week
  beginner default → 4), `runs_per_week_effective` = min(choice or recommended,
  available days, 6).
- Generator: same weekly volume split over the effective count. **15-min rule applies to
  every plan, not only explicit choices**: a week whose non-long sessions would be under
  15 min total gets fewer runs (never fewer than 2). Plan `summary.notes` lists those
  weeks ("Week of 19 Oct: 5 runs instead of 6 — …"); `summary.runs_per_week` stores the choice.
- Re-layout (`planning/relayout.py`, `apps/planning/relayout.py`): only **plan weeks**
  (7-day blocks from the first phase start, the generator's own weeks) that start after
  today, contain no RACE and only `planned` workouts. The current partial week is never
  re-laid. A week is regenerated only when its run count differs from the target. Week
  volume = the stored prescribed run seconds (adaptation already applied to those rows,
  so it is kept — not re-applied twice); walking seconds kept too; phase from the rows.
  Rows are rewritten in place (same kind first) so watch copies are re-sent (`watch_updated`);
  surplus rows and WALKs on a new run date are deleted (`dropped`, `watch_removed`).
  The long run keeps its share of the week, so it usually does not change.
- Triggers on PATCH /api/athlete/: `runs_per_week` changed, or days/long-run day changed
  **while an explicit `runs_per_week` is set** (re-flow first, then re-layout). With
  "Auto" (null) a days change keeps the earlier re-flow behaviour (drops). The re-flow's
  limit is the explicit choice when set.
- `plan_reflow` (when not null) is now always `{moved, dropped, watch_updated,
  watch_removed, regenerated, notes}` (re-flow and re-layout summed). `notes` can be
  non-empty with `regenerated: 0`. Record appended to `summary.reflows` with reason
  "runs per week changed".

**§B habits** (`apps/habits`, `analysis/habits.py`)
- Log JSON: `{id, kind, quantity, at, local_date, note, created_at}`. quantity 0.1–100
  (default 1); `at` > 5 min in the future → 400; note ≤ 200. GET list: newest first, max
  1000, default last 90 days when neither `start` nor `end` given; bad date → 400.
- `GET /habits/today/` `last_at` values are the last log time ever (null if none).
- Summary extra keys: `today`, `goals` {smoke, alcohol, sugar}. Impact rows have extra
  `dose` (null, or "1-2"/"3+" for alcohol HRV rows, shown only when both dose groups have
  ≥ 3 nights). All impact rows are returned (UI filters on `enough_data`). Impact metric
  keys: hrv, rhr, sleep_score, body_battery, stress, sleep_respiration (±0.5 brpm), easy_hr,
  efficiency (±3 %), hr_drift (±1 pt). Days considered: from the first log of that habit
  (or quit date for smoke) to yesterday; metrics are the DailyMetrics dated the next day.
- **Averages** divide by the range window, or by the days since the first-ever log of
  that habit when shorter (minimum 7 days) — never by days with data. `per_day_avg` /
  `per_week_avg` are null when the habit was never logged.
- Streak: zero-cigarette days counted from the quit date or first log (whichever is
  earlier); today counts while clean. `since_quit` null without a quit date;
  `cigarettes_avoided` = max(baseline × days − smoked since quit, 0) (null without
  baseline); `money_saved` a number in ₹ (null without price). Milestones count from the
  later of the quit date (local midnight) and the last cigarette logged after it.
- `POST /habits/summary/?range=&refresh=1` → `{status, markdown, generated_at}` (like
  insights), not the full payload. Cached per day; `refresh=1` deletes today's row and
  regenerates. 503 `{detail}` on AIUnavailable/budget; 429 throttle scope `chat`. The
  model gets aggregates only (no series, rows, times or notes); money as "₹2,448".
- Morning check-in: signal `alcohol` only when yesterday's drinks ≥ 3 (watch) / ≥ 5 (bad),
  label "3 drinks last night", value = drinks. Never "good", never in `signals_missing`.
- Chat tool `log_habit(kind, quantity, at?)` (future `at` → now; note "via chat");
  system prompt `habits: {today, yesterday, goals, smoke_free_streak_days,
  days_since_quit}` when the athlete tracks anything.
- Insights focus: `smoke_free` (smoke days in last 14 > the 14 before) and `alcohol`
  (12-week alcohol→HRV row with enough_data and direction worse).
- Athlete fields: `smoke_goal` (quit|reduce|none, default none), `smoke_quit_date`,
  `smoke_baseline_per_day` (0–100), `cigarette_price` (0–10000), `alcohol_goal`,
  `sugar_goal` (reduce|none), `daily_limits` ({smoke?, alcohol?, sugar?: number 0–100 | null}).

**§C progress** (`analysis/progress.py`, `apps/activities/progress*.py`)
- `GET /progress/?window=1|5|10|20&sport=running|walking` (else 400). Extra keys:
  `window, runs, current_n, previous_n, sport, today, review`. Runs: last 365 days, max
  300, with segmented running. window=1 compares the last run with the 5 before.
- `metrics`: 12 rows, keys `run_km, total_km, run_pace, avg_hr, max_hr, easy_hr,
  efficiency, hr_drift, cadence, run_fraction, longest_run_s, z2_pct` (units km, km, s/km,
  bpm, bpm, bpm, m/min/bpm, %, spm, %, s, %). Values are per-run means. `run_fraction`
  in percent. `better` null when |delta_pct| < 1 %, either side missing, or for avg/max
  HR; cadence better = closer to 168 spm. easy_hr = duration-weighted HR of run blocks
  whose pace is within easy_pace_min−15 … easy_pace_max+30 s/km.
- `distance_buckets`: `[{bucket: lt2|2to5|5to8|8plus, label, runs, current_n,
  previous_n, metrics}]` by total distance. `bests`: `{fastest_1k_s, longest_run_km,
  longest_continuous_s, lowest_easy_hr}` each `{value, date, activity_id, new}` or null
  (fastest 1 km from the distance stream, cached per activity). `series`: last
  max(2×window, 40) runs `{date, activity_id, run_km, total_km, pace, avg_hr, efficiency,
  cadence, bucket}`. `focus`: `[{key, kind: improve|check, title, why, how}]`, ≤ 4.
- `POST /progress/review/?window=&refresh=1` → `{status, went_well, improve, check,
  markdown, generated_at}`; 409 with no runs; 503 AIUnavailable; cached per window per day.
  `GET /progress/` carries the same object as `review` (status none until generated).

**§D weather** (`analysis/weather_advice.py`, `apps/ingest/weather*.py`)
- `GET /weather/today/` always 200. Extra keys: `available`, `reason` (null |
  "no_location" | "unavailable"), `daily {temp_max, temp_min, feels_like_max}`, `heat`
  (cool|warm|hot|very_hot), `pace_slowdown_pct` (0/3/8/12). When unavailable: `now`,
  `hydration`, `best_window`, `heat` null, lists empty, bonus 0.
- `hourly[]`: next 24 h from the current hour `{time ("YYYY-MM-DDTHH:MM" local), temp,
  feels_like, humidity, dew_point, precip_prob, wind (km/h), uv, weather_code,
  condition, aqi, pm25}`. `best_window {start, end, reason}` local ISO minutes, 1 h, may
  be tomorrow morning. Advisory `level`: info | caution | warning.
- Hydration uses the best-window conditions and today's planned workout duration:
  `during_ml_per_h` 0 when the run is < 45 min (band value when nothing is planned).
  Water bonus / food tips use today's max feels-like.
- Location: `location_city` (writable; geocoded on save; not found or outage → 400
  `{location_city: [...]}`; "" clears → back to runs). Read-only `location_lat/lon`
  (2 dp), `location_name` ("Near your recent runs" for source runs), `location_source`.
  Runs location = first GPS record of the latest run, re-derived on read.
- Cache: Django cache (Redis) per rounded lat/lon + timezone + UTC hour, 1 h; 5 s timeout.
- Check-in: `heat` (watch) when even the best window is hot (feels ≥ 32 °C or dew ≥ 24 °C);
  `air` watch AQI > 100, bad > 200. Neither ever "good" nor in `signals_missing`.
- Diet day: `targets.water_ml` includes the bonus, new `targets.water_bonus_ml`, top-level
  `weather_tips: [str]`, `fueling[].weather_note` (str | null) — today only.
- `GET /workouts/{id}/` gains `weather`: null unless the workout is today; else
  `{available:false, reason}` or `{available, location_name, now, best_window, advisories,
  hydration, heat, pace_slowdown_pct, fueling_note}`.

**§E** Account deletion removes HabitLog (cascade) and location (Athlete row); per-activity
progress cache keys are deleted too.

## R9 (SPEC_R9.md) — additions and choices

Field names follow the spec exactly; everything below is either an extra field or a
choice the spec left open.

**§B private habit** (`apps/habits`, migrations `athletes.0007_r9_private_habit`,
`habits.0002_r9_private_kind`)
- Athlete JSON (writable): `private_habit_enabled` (bool, default false),
  `private_on_today` (bool, default false), `private_goal` (`reduce|none`, default none;
  anything else → 400). `daily_limits` also accepts a `private` key.
- `HabitLog.kind` gains `private` (label "Private").
- **Disabled**: `GET /habits/today/` `counts` / `last_at` have no `private` key;
  `GET /habits/summary/` has no top-level `private`, no `goals.private`, no private
  impact rows and no private report card. `POST /habits/logs/ {kind: "private"}` → 400
  `{kind: ["Turn on the Private habit in Settings first."]}`. PATCH of an existing private
  log is also 400 while disabled; single `DELETE /habits/logs/{id}/` still works.
  `GET /habits/logs/` without `kind` hides private logs while disabled; `?kind=private`
  still lists them (so Settings can show what "Delete private logs" removes).
- **Enabled**: `today.counts.private`, `today.last_at.private`; summary gets
  `private: {series, total, per_day_avg}` (same shape as `sugar`), `goals.private`,
  impact rows with `habit: "private"` and a `report.habits[]` card.
- `DELETE /habits/logs/?kind=private` → 200 `{deleted: n}` (the requester's own logs only,
  enabled or not). `kind` is required for a bulk delete (400 without it, 400 for an unknown
  kind); any kind (smoke|alcohol|sugar|private) is accepted.
- Never to the AI: chat `log_habit` rejects `private` ("kind must be smoke, alcohol or
  sugar."), chat system prompt `habits` block only ever has smoke/alcohol/sugar (and is
  omitted when only private logs exist), the AI habits summary input drops the private
  block, goal, impact rows and report card (and recomputes `report.overall` without it, so
  even the habit count does not hint at it), and check-in signals never read it.
- Impact-row labels for it read "… the morning after a Private day …".

**§C habit health report** (`analysis/habits.py`: `habit_report`, `garmin_compare`,
`overall`, `report`, `spearman`) — `GET /habits/summary/?range=` gains:
```
report: {
  overall: {status, headline},
  garmin: [{metric, label, unit, now, before, delta, better}],
  habits: [{habit, status, headline,
            amount: {now_per_day, before_per_day, change_pct, now_per_week, before_per_week},
            findings: [{tone, text, kind}]}]
}
```
- Previous range = the same number of days just before the range (4w → 28 days before).
  Headlines say "the previous 4 weeks" / "12 weeks" / "6 months".
- `garmin[].metric` order: hrv, rhr, sleep_score, stress, body_battery_high, respiration
  (sleep breathing rate), easy_pace_hr (HR on easy-pace runs), efficiency. A side needs
  ≥ 3 days with a value, else null; `better` uses the R8 impact thresholds (HRV ±5 %,
  RHR ±2 bpm, sleep ±3, stress ±3, Body Battery ±5, breathing ±0.5, easy HR ±2,
  efficiency ±3 %), null when below or a side is missing.
- `habits[]` lists only habits that have ever been logged or have a goal (smoke: or a quit
  date); private only when enabled. Order smoke, alcohol, sugar, private.
- `amount`: per-day averages over the *tracked* days of each range (from the first log /
  quit date); extra `now_per_week` / `before_per_week` (alcohol is phrased per week).
  `change_pct` null when the previous range was 0 and this one is not. A trend needs ≥ 7
  tracked days in both ranges, else `status: not_enough_data`.
- `findings[].kind`: `amount`, `next_morning`, `dose` (alcohol), `timing`
  (alcohol/sugar/private), `weekly_link`, `since_quit` (smoke), `next_day_run`,
  `keep_logging` (one neutral item, last, listing every finding still short of data, with
  the counts so far). Thresholds as spec: next-morning = R8 impact rows with enough_data
  (morning metrics only; no-clear-difference rows collapse into one neutral line);
  dose ≥ 3 nights each of 1–2 vs 3+ (HRV and sleep score); timing = a log at ≥ 21:00 local
  that day vs exposure days without one, ≥ 4 nights each (sleep score, HRV); weekly link =
  Spearman over full 7-day blocks ending today (only blocks after tracking began, metric
  needs ≥ 3 mornings in the block), ≥ 6 weeks, reported at |ρ| ≥ 0.4 (else one neutral
  "no clear weekly link" when there were enough weeks; not mentioned at all for 4w, which
  can never reach 6 weeks); since quit = quit date ≥ 7 days ago, 14 days before vs every
  day since, ≥ 5 days each for HRV / RHR / sleep score / easy-pace HR; next-day run = runs
  the day after an exposure vs a clean day within the range, ≥ 3 each (easy-pace HR,
  efficiency). Tones: worse → bad, better → good, else neutral (an association in the
  "better" direction for dose/timing/weekly link is neutral, not good).
- Habit `status`: amount down ≥ 10 % with no *new* bad finding → improving (new bad = a
  bad next-morning metric that was not already worse with enough data in the previous
  range, or any bad since-quit finding); up ≥ 10 % → worsening; else steady.
  `headline`: "Down 38% vs the previous 4 weeks" / "Up 25% vs …" / "Up from none in …" /
  "About the same as …" / "None logged here or in …" / "Keep logging to see a trend".
- `overall.status`: not_enough_data when no habit has a trend; improving when more than
  half of those habits are improving and neither HRV nor RHR is worse; worsening when more
  than half are worsening; else steady. Headline e.g. "2 of 3 habits improving vs the
  previous 4 weeks; HRV 45 → 50 ms, resting HR 58 → 56 bpm".
- `POST /habits/summary/?refresh=1` sends `report` (minus private) to the model.
- Insights focus still calls the summary without the report (`with_report=False`).

**§D progress dates + highlights** (`analysis/progress.py`: `progress_dates`,
`highlights`, `bucket_rows`; `apps/activities/progress*.py`)
- `GET /progress/?start=&end=[&compare_start=&compare_end=][&sport=]`. 400 `{detail}`
  messages: window and dates together ("Use either window or start/end dates, not
  both."), only one of start/end ("start and end are both required …"), bad date
  ("… must be a date (YYYY-MM-DD)."), start > end, range > 730 days inclusive, only one
  of compare_start/compare_end ("… go together."), compare_start > compare_end, compare
  range > 730 days. Default compare = the same number of days just before `start`. The
  same parameters and validation apply to `POST /progress/review/`.
- Date mode body: same keys as window mode; `window: null`; `runs` = runs inside the
  current + compare ranges; `distance_buckets` compare the two ranges per bucket (not the
  last-N split); `bests` are over the year before the earlier range up to `end`
  (`new` = set inside the range); `series` = runs in the two ranges (oldest first, max
  200). Up to 600 runs are read in date mode.
- `period: {mode: "window"|"dates", start, end, compare_start, compare_end,
  runs_current, runs_previous}` in both modes (ISO dates). Window mode: start/end = dates
  of the first/last current run, compare_* = first/last previous run (null when none).
- `highlights: [{tone: "good"|"bad"|"neutral", text}]`, max 6, sorted good → bad →
  neutral. Sources: metric rows with a non-null `better` (run pace "Run pace 7:12 → 6:58
  /km — 14 s faster", easy HR, efficiency, run distance, run fraction, longest continuous
  run, cadence vs 168, drift, Z2), new bests in the period (only when there were earlier
  runs: "New best: fastest 1 km in 5:33 (2026-09-30)"), one like-for-like bucket pace line
  ("2–5 km runs: run pace … (4 vs 3 runs)", skipped when one bucket holds every run),
  consistency ("Consistency 1.5 → 3.0 runs/week", ±0.5 runs/week is "Consistency steady
  at …"). Pinned neutral lines kept at the end: "No runs in this period" (then the only
  item), "Only one run in this period" (date mode, or window mode with no earlier runs),
  "No runs in the previous period to compare with" / "No earlier runs to compare with yet".
  If nothing moved: "Much the same as before — no measure moved more than 1%".
- Review cache: rows tagged with the window (1/5/10/20) or
  `"dates:<start>:<end>:<compare_start>:<compare_end>"`; `GET /progress/` with the same
  params returns that review. The model also gets `period` and `highlights`.

**§E guides** (`analysis/guides.py`, `apps/coaching/guides.py`)
- `GET /guides/` → `{for_you: [{key, reason, priority}], context: {window_days: 28, runs,
  cadence_avg, metronome_bpm, hr_drift_runs, run_fraction_pct, smoking, feels_like_max,
  longest_upcoming_run_min, weather_available, hydration}}`.
- Keys: form | breathing | strength | fueling | warmup. `priority` 1 (most relevant) … 5;
  sorted by priority then that key order; duplicates merged (reasons joined with " · ",
  best priority kept). Priorities: HR drift > 5 % on ≥ 2 runs → breathing + fueling (1);
  cadence < 160 → form (2); run fraction < 0.85 → strength + breathing (2); feels-like
  max ≥ 28 °C or a planned non-walk run ≥ 60 min from today to Sunday → fueling (2);
  smoke goal quit/reduce or a cigarette logged in 28 days → breathing (3); warmup always (5).
- `metronome_bpm` = average cadence × 1.05, rounded, clamped 140–200; 165 without cadence.
- Weather comes only from this hour's cached Open-Meteo response for the athlete's
  location (`weather.cached_only`, never a network call). No location, nothing cached or a
  broken entry → `weather_available: false`, `feels_like_max` / `hydration` null.
  `hydration` has the `/weather/today/` shape `{before_ml, during_ml_per_h, after_note,
  electrolytes}`. Diet targets for the fueling guide come from the existing diet endpoint.

## R10 (SPEC_R10.md) — contract for §B (Garmin data) and §C (features)

All paths are under `/api/`, need a signed-in athlete (401 otherwise) and only ever read
or write the requester's own rows. Dates are ISO `YYYY-MM-DD`; datetimes ISO 8601 with
offset; local clock times are `"HH:MM"` (24 h) in the athlete's timezone. Any field
marked `|null` is `null` when Garmin / the data does not provide it — the UI hides it.
Errors are `400 {detail: str}` unless noted.

**Ranges.** Every `?range=` below accepts `7d | 4w | 3m | 6m | 1y` (7, 28, 91, 182, 365
days ending today, inclusive). Anything else → 400 `{detail}`. Defaults: fitness 6m,
sleep 4w, form 3m, body 6m, compare 3m. Every ranged body carries
`range: str, start: date, end: date`.

### B1/B3 `GET /health/fitness/?range=`
```
{ range, start, end,
  vo2max:          {current: float|null, change: float|null, series: [{date, value: float}]},
  fitness_age:     {current: float|null, chronological_age: int|null,
                    achievable: float|null, change: float|null,
                    series: [{date, value: float}]},
  endurance_score: {current: int|null, level: str|null, change: int|null,
                    series: [{date, value: int}]},
  race_predictions: {current: Pred|null, previous: Pred|null,
                     as_of: date|null, previous_as_of: date|null,
                     series: [{date, "5k_s", "10k_s", "half_s", "marathon_s"}]},
  lactate_threshold: null | {hr: int|null, pace_s_per_km: int|null, date: date,
                     source: "garmin", zones_updated: bool, zones_updated_at: datetime|null,
                     series: [{date, hr: int|null, pace_s_per_km: int|null}]},
  zones: Zones|null }
Pred = {"5k_s": int|null, "10k_s": int|null, "half_s": int|null, "marathon_s": int|null}
```
- `change` = latest value in the range minus the first value in the range (null with
  fewer than 2 values). Race predictions: `previous` = the first prediction in the range;
  lower seconds = faster.
- `endurance_score.level`: Garmin classification as words (Recreational, Intermediate,
  Trained, Well-trained, Expert, Superior, Elite) or null.
- `zones_updated` is true for 14 days after the LT changed the zones.
- `Zones` = the athlete's `zones` object (below).

**Athlete `zones` gains keys** (existing keys unchanged): `source: "heart_rate_reserve" |
"lactate_threshold"`, `lt_hr: int|null`, `lt_date: date|null`, `updated_at: datetime|null`,
`capped: bool` (true when the safety rule below lowered an LT-derived easy bound).
`resting_hr` may be null when the zones come from the LT alone.

**LT → zones safety rule.** Zones switch to the lactate threshold only when Garmin has
an LT heart rate (120–210 bpm, below max HR when known). LT zones (fractions of LTHR,
Friel running): Z1 0.65–0.85, Z2 0.85–0.89, Z3 0.89–0.94, Z4 0.94–1.00, Z5 1.00–max HR
(max = known max HR, else LTHR × 1.06). **Easy zones can never get harder:** Z1 and Z2
bounds are each `min(LT value, heart-rate-reserve value, hr_ceiling)` (HRR zones when they
can be computed), so an easy run never targets a higher HR than before; Z3 then starts at
Z2's top. The LT, its date and source are stored on the athlete (`lt_hr`, `lt_pace_s`,
`lt_date`, `zones_source`, `zones_updated_at`); a newer LT only rewrites them when the HR
or pace changed. Without LT data nothing changes.

### B2 `GET /health/training-status/`
```
{ date: date|null, status: str|null, status_key: str|null,
  acute_load: float|null, chronic_load: float|null, acwr: float|null,
  load_focus: null | {date: date, feedback: str|null, period_days: 28,
     items: [{key: "low_aerobic"|"high_aerobic"|"anaerobic", label: str, value: float,
              target_min: float|null, target_max: float|null,
              state: "below"|"in_range"|"above"|null}]},
  history: [{date, status_key: str|null, acute_load: float|null, chronic_load: float|null}] }
```
- `status` e.g. "Productive"; `status_key` one of productive, maintaining, recovery,
  unproductive, detraining, peaking, overreaching, strained, no_status (null if unknown).
- `feedback` e.g. "Below targets" (Garmin's phrase in words). `history` = last 28 days,
  oldest first. Everything comes from the latest day that has it.

### B4 `GET /health/sleep/?range=` (default 4w)
```
{ range, start, end,
  nights: [{date, sleep_s: int|null, need_s: int|null, score: int|null,
            deep_s, light_s, rem_s, awake_s: int|null,
            bedtime: "YYYY-MM-DDTHH:MM"|null, wake_time: "YYYY-MM-DDTHH:MM"|null,
            restless_moments: int|null, spo2_avg: float|null, spo2_low: float|null,
            breathing_rate: float|null}],
  averages: Avg, previous: Avg,
  regularity: {bedtime_sd_min: int|null, previous_bedtime_sd_min: int|null, n: int,
               better: bool|null},
  debt: {need_s: int|null, debt_s: int|null, short_nights: int, nights: int,
         short_by_s: int|null},
  sleep_vs_runs: {short_h: 6, long_h: 7, short: {easy_hr: float|null, n: int},
                  long: {easy_hr: float|null, n: int}, diff_bpm: float|null,
                  enough_data: bool, sentence: str|null},
  tonight: {need_s: int|null, wake_time: "HH:MM"|null, bedtime: "HH:MM"|null} }
Avg = {sleep_s: int|null, need_s: int|null, score: int|null, deep_s: int|null,
       rem_s: int|null, spo2_avg: float|null, breathing_rate: float|null,
       restless_moments: int|null, bedtime: "HH:MM"|null, wake_time: "HH:MM"|null}
```
- A night is dated by the morning it ends (Garmin's convention). `nights` oldest first,
  only nights with any sleep data. `previous` = the same-length range just before.
- Regularity = standard deviation of bedtime (minutes; bedtimes after midnight count as
  24:xx), needs ≥ 3 nights (else null); `better` = SD at least 5 min lower than previous.
- Debt = the last 7 nights with both values: Σ(need − actual), never below 0 (`debt_s`);
  `need_s` = median need; `short_nights` = nights under need; `short_by_s` = mean shortfall
  on those nights.
- Sleep vs runs: HR on easy-pace runs the day after a night < 6 h vs ≥ 7 h, within the
  range; `enough_data` needs ≥ 3 runs on each side.
- Tonight: median wake time of the last 7 nights; bedtime = wake − need − 15 min.

### B5 `GET /health/form/?range=` (default 3m)
```
{ range, start, end, has_dynamics: bool,
  runs: [{activity_id, date, cadence_spm: float|null, ground_contact_ms: float|null,
          vertical_oscillation_cm: float|null, stride_length_m: float|null,
          run_km: float, run_pace_s_per_km: float|null}],
  metrics: [{key: "cadence"|"ground_contact"|"vertical_oscillation"|"stride_length",
             label, unit, current: float|null, previous: float|null, change: float|null,
             better: bool|null, trend_per_week: float|null, n: int}] }
```
- `current` = mean of the last 5 runs in range with the value, `previous` = the 5 before.
  `better`: cadence closer to 168; ground contact / vertical oscillation lower; stride
  length null (not good/bad by itself). Null below 1 % change.

### B6 `GET /health/records/`
```
{ records: [{key, label, source: "garmin"|"computed", unit: "s"|"m", value: float,
             display: str, date: date|null, activity_id: int|null,
             garmin_activity_id: int|null, is_new: bool}],
  new_count: int, synced_on: date|null }
```
- Garmin keys (in this order, only the ones Garmin has): `1k`, `mile`, `5k`, `10k`, `half`,
  `marathon` (unit s), `longest_run` (unit m). Computed keys (from our own runs):
  `fastest_1k` (s), `longest_distance` (m), `longest_continuous` (s, longest unbroken run
  block). `display` "27:15", "1:02:15", "10.2 km".
- `is_new` = set within the last 14 days. `activity_id` = our Activity when matched.

### B7 `GET /health/body/?range=` (default 6m)
```
{ range, start, end, profile_weight_kg: float|null,
  latest: null | {date, weight_kg: float|null, body_fat_pct: float|null, bmi: float|null,
                  muscle_mass_kg: float|null, source: "garmin"|"manual"},
  change: {weight_kg: float|null, body_fat_pct: float|null},
  trend_kg_per_week: float|null,
  series: [{date, weight_kg: float|null, body_fat_pct: float|null,
            source: "garmin"|"manual"}] }
```
- Garmin weigh-ins merged with manual weight entries (one point per day; Garmin wins).
  A Garmin weigh-in newer than every weight entry also becomes a `MetricEntry` (source
  garmin), so the profile weight — and so Diet — uses it.

### B8 Gear — `GET/POST /gear/`, `PATCH/DELETE /gear/{id}/`
```
GET  -> {shoes: [Shoe], default_retire_km: 700}
Shoe = {id, name, brand: str, source: "garmin"|"local", is_default: bool, retired: bool,
        retire_km: float, start_km: float, distance_km: float, activities: int,
        in_use_since: date|null, last_used: date|null, remaining_km: float,
        replace_soon: bool, replace_due: bool, garmin_uuid: str|null, created_at}
```
- Order: active first, default first, then newest. Garmin shoes: distance/activity count
  from Garmin's gear stats; `retire_km` from Garmin's max distance (else 700).
  Local shoes: `start_km` + runs assigned to the shoe. Running activities with no shoe
  dated on/after a local default shoe's `in_use_since` (else its creation date) are
  auto-assigned to it.
- `replace_soon` ≥ 90 % of `retire_km`, `replace_due` ≥ 100 %.
- POST `{name (1–80, required), brand?, retire_km? (100–2000), start_km? (0–5000),
  is_default?, in_use_since?}` → 201 Shoe (local). Making one default clears the others.
- PATCH local: any of those + `retired`. PATCH a Garmin shoe: only `retire_km`,
  `is_default`, `retired` (other keys → 400). DELETE local → 204; Garmin → 400.
  Another athlete's id → 404.

### C9 Lung recovery `GET /habits/lung-recovery/`
```
{ available: bool, reason: null|"no_quit_date"|"quit_date_in_future",
  quit_date: date|null, days_since_quit: int|null,
  metrics: [{key: "sleep_breathing_rate"|"spo2"|"resting_hr"|"easy_hr", label, unit,
             before: float|null, before_n: int, now: float|null, now_n: int,
             change: float|null, better: bool|null, enough_data: bool,
             series: [{date, value: float}], sentence: str}],
  milestones: [{label, reached: bool, at: datetime}],
  note: str }
```
- before = the 14 days before the quit date; now = the last 14 days (since the quit date
  when that is shorter). `enough_data` needs ≥ 5 values each side. Thresholds for
  `better` as R8 impact (breathing ±0.5, SpO2 ±1 point, RHR ±2, easy HR ±2). Series from
  quit − 14 days to today. Sentences describe association only ("…since you quit — this
  can't show the cause"). `available: false` → `metrics: []`, `milestones: []`.

### C10 Weekly report
`GET /reports/weekly/?week=YYYY-MM-DD` (any date in the wanted Monday–Sunday week;
default = last complete week). The current or a future week → 400. Built and stored on
first read if the Monday 06:00 job has not run yet.
```
{ id, week_start, week_end, generated_at,
  runs: {done: int, planned: int, planned_done: int, km: float, run_km: float,
         time_s: int, previous_done: int, previous_km: float},
  zones: {Z1, Z2, Z3, Z4, Z5, below: int (seconds)} | {}, zones_total_s: int,
  prs: [{key, label, display, date}],
  wellness: [{metric: "hrv"|"rhr"|"sleep"|"sleep_score", label, unit,
              this_week: float|null, previous_week: float|null, delta: float|null,
              better: bool|null}],
  habits: [{habit: "smoke"|"alcohol"|"sugar"|"private", label, this_week: float,
            previous_week: float, delta: float, better: bool|null}],
  went_well: [str], to_improve: [str], goal: str,
  ai: {status: "none"|"ready", markdown: str, generated_at: datetime|null} }
```
- `GET /reports/weekly/list/` → `[{id, week_start, week_end, runs_done, km, generated_at}]`
  newest first, max 52.
- `POST /reports/weekly/ai/?week=` → `{status, markdown, generated_at}` (coach tier,
  cached per report; `?refresh=1` regenerates). 503 `{detail}` when AI is unavailable or
  the budget is used; 429 throttle scope `chat`. The model gets the report minus the
  private habit (and nothing per-day).
- `habits` lists only tracked habits (logged in either week or with a goal); `private`
  only when enabled. Fewer than 2 runs/night values → wellness side null.
- Beat: hourly; an athlete is built when it is Monday 06:xx in their timezone (idempotent).

### C11 Compare any two
`GET /health/compare/metrics/` →
`{metrics: [{key, label, unit, group: "wellness"|"habits"|"runs", noun: str}]}`.
Keys — wellness: `sleep_h, sleep_score, hrv, rhr, stress, body_battery, breathing_rate,
spo2, steps, bedtime_h, training_load`; habits: `smoke, alcohol, sugar` (+ `private` only
when enabled); runs (by run date, mean of the day's runs): `run_km, run_pace, easy_hr,
avg_hr, efficiency, cadence, hr_drift, run_fraction`. `bedtime_h`: 22.5 = 22:30, 25.0 = 01:00.

`GET /health/compare/?x=&y=&range=&lag=0|1` (lag default 0; 1 = y the day after x)
```
{ x: {key, label, unit}, y: {key, label, unit}, range, start, end, lag: int,
  points: [{date, x: float, y: float}], n: int, rho: float|null,
  strength: "none"|"weak"|"moderate"|"strong"|null,
  direction: "positive"|"negative"|null, enough_data: bool,
  trend: {slope: float, intercept: float}|null, sentence: str, caveat: str }
```
- Unknown key, x == y, `private` while disabled, lag not 0/1 → 400 `{detail}`.
- Habit days count from the first log (0 on days without one). `enough_data` n ≥ 8;
  strength by |ρ|: < 0.2 none, < 0.4 weak, < 0.6 moderate, else strong. ρ to 2 dp.
- Sentence e.g. "Days with more sleep tended to be followed by lower HR at easy pace
  (ρ = −0.48, n = 22)." Compare is never sent to the AI.

### C12 Reminders (web push)
- `GET /reminders/` →
  `{available: bool, public_key: str|null, subscriptions: int, ios_note: str,
    reminders: [{key, label, description, enabled: bool, time: "HH:MM"}]}`.
  Keys: `morning_checkin` (07:00), `habit_log` (21:00), `best_run_time` (06:00),
  `weekly_report` (Mondays, 07:00). All off by default.
- `PATCH /reminders/` `{<key>: {enabled?: bool, time?: "HH:MM"}, …}` → same as GET.
  Bad key / time → 400.
- `POST /reminders/subscribe/` `{endpoint: https URL, keys: {p256dh, auth}}` → 201
  `{id, created: bool}` (200 with `created: false` when already stored).
- `POST /reminders/unsubscribe/` `{endpoint}` → `{deleted: int}` (own rows only).
- `POST /reminders/test/` → `{sent: int, failed: int}`.
- `available` is false unless `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT`
  are all set; then subscribe/test → 503 `{detail}` and nothing is sent (GET/PATCH still
  work). Push payload `{title, body, url, tag}`; no habit counts or health numbers in it.
- Beat every 5 min: a reminder is sent once per local day, from its time up to 2 h after.
  `best_run_time` needs a weather best window; `weekly_report` only on Mondays with a
  report. Expired subscriptions (404/410) are deleted.

### C13 Achievements
- `GET /achievements/` →
```
{ badges: [{key, group, label, description, target: int, unit: str, earned: bool,
            earned_on: date|null, progress: {current: int, target: int}, new: bool}],
  recent: [{key, kind: "badge"|"pr", label, earned_on: date}], unseen: int }
```
  Groups/keys: smoke_free (`smoke_free_1|3|7|14|30|90`, days; only when smoking is
  tracked), consistency (`consistent_weeks_2|4|8|12`: consecutive Mon–Sun weeks with ≥ 2
  runs), distance (`first_5k`: a run ≥ 5 km), records (`prs_1|5|10`: personal-record
  events), run_streak (`run_streak_3|5|7`: consecutive days with a run), sleep
  (`sleep_7h_3|7|14|30`: consecutive nights ≥ 7 h). `earned_on` = the day it was reached,
  stored once (idempotent). `recent` = last 10 earned (badges and PR events).
- `POST /achievements/seen/` → `{updated: int}` (clears `new`).

### C14 `GET /health/readiness-forecast/`
```
{ date: date (tomorrow), estimate: int|null, low: int|null, high: int|null,
  label: str, is_estimate: true,
  today: {score: int|null, source: "garmin"|"computed"|null},
  factors: [{key: "load"|"hrv_trend"|"sleep_debt"|"alcohol"|"smoke", label, effect: int,
             detail: str}],
  levers: [{key: "bedtime"|"no_alcohol", label: str, gain: int}],
  best_case: int|null, sentence: str, note: str }
```
- Deterministic; `estimate` null (with a sentence saying why) when there is no readiness
  data in the last 3 days. Private habit is never an input.

### R10 backend choices (and where the spec was silent)
- **Garmin methods** (garminconnect 0.3.10, pin unchanged): `get_endurance_score(date)`
  (one day, precise) / `(start, end)` (weekly groups), `get_fitnessage_data(date)`,
  `get_lactate_threshold(latest=True)` / `(latest=False, start_date, end_date)`,
  `get_personal_record()`, `get_body_composition(start, end)`, `get_user_profile()`
  (only when no stored sleep payload carries `userProfilePK`), `get_gear(profile_pk)`,
  `get_gear_stats(uuid)` (≤ 10 per run). Training status / load focus come from
  `get_training_status` and sleep details (restless moments, SpO2) from `get_sleep_data`,
  both already fetched daily — no new per-day calls. There is no range call for fitness
  age; the backfill samples it weekly.
- **Once a day**: `ingest.sync_slow_one` (garmin queue) is queued 30 s after a successful
  sync (scheduled or manual) unless `GarminProfile.slow_synced_on` is already today. The
  breaker is checked before every call, calls are `GARMIN_SLOW_PAUSE_S` (1.5 s) apart, the
  first 429 stops the run and trips the breaker, and the day is only marked done when the
  run finished. An endpoint that errors (not a 429) is just skipped (stored as null).
- **Backfill**: `python manage.py garmin_backfill_r10 --athlete ID [--days 180] [--now]`
  or `--all` (queued 10 min apart on the garmin queue; `--now` runs inline). Refuses while
  the breaker is open. Also re-maps every stored raw payload into the new columns.
- **LT speed** from Garmin is sometimes in tenths of m/s; a value below 1 is multiplied by
  10 (no runner's threshold is under 1 m/s). Pace = 1000 / speed.
- **Endurance score history** from the range call lands on each week's first day (weekly
  average); daily values come from the daily fetch.
- **Weight → Diet**: the newest Garmin weigh-in becomes a `MetricEntry(source="garmin")`
  only when it is newer than every weight entry, so a manual entry made later still wins.
- **Weekly report AI paragraph** is on demand (`POST /reports/weekly/ai/`, like the other
  AI summaries), not generated by the Monday job — no model spend for reports nobody
  opens. The Monday job builds the deterministic card only. Went-well / to-improve / goal
  are re-derived on every read, so turning the private habit off also removes its lines.
- **Compare dates**: wellness values use Garmin's date (sleep on a date = the night that
  ended that morning), so `x=sleep_h&y=easy_hr&lag=0` already means "the night before the
  run"; `lag=1` shifts y one more day. `training_load` counts 0 on days without training
  (from the first activity).
- **Achievements**: badges reached more than 7 days before they are first stored (history,
  a first sync) are stored as seen, so the first visit is not a flood of toasts. Once
  stored a badge is never taken away. PR events are stored as `kind: "pr"` rows
  (`pr:<source>:<key>:<date>`) and counted for `prs_*`; computed bests count too.
- **Reminders**: a reminder whose message cannot be built (no weather best window today,
  `weekly_report` on a non-Monday) is skipped for that day. A subscription is deleted on
  404/410 or after 10 consecutive failures. Generating the VAPID pair (run once; put the
  output in `deploy/secrets/prod.env`):
  ```
  python -c "import base64; from py_vapid import Vapid02 as V; from cryptography.hazmat.primitives import serialization as s; v=V(); v.generate_keys(); b=lambda x: base64.urlsafe_b64encode(x).decode().rstrip('='); print('VAPID_PRIVATE_KEY='+b(v.private_key.private_numbers().private_value.to_bytes(32,'big'))); print('VAPID_PUBLIC_KEY='+b(v.public_key.public_bytes(s.Encoding.X962, s.PublicFormat.UncompressedPoint)))"
  ```
  The frontend passes `public_key` as `applicationServerKey` to `pushManager.subscribe`.
- **Records**: the computed `fastest_1k` label is "Fastest 1 km split"; computed bests
  look at the last 12 months of runs (the progress window).
- **Account deletion**: every R10 table cascades from the Athlete (GarminProfile,
  PersonalRecord, BodyComposition, LactateThreshold, Shoe, ShoeAssignment, WeeklyReport,
  Achievement, PushSubscription, ReminderSettings).
- New env: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (secrets),
  optional `GARMIN_SLOW_PAUSE_S`. New dependency: `pywebpush` (rebuild the image).

## R11 (SPEC_R11.md) — contract for Day, nudges, water and run maps

Same conventions as R10: every path is under `/api/`, needs a signed-in athlete (401
otherwise) and only reads/writes the requester's own rows (another athlete's id → 404).
Dates `YYYY-MM-DD`; datetimes ISO 8601 with offset; clock times `"HH:MM"` (24 h, athlete's
timezone). **`min` = minute of the local day, an int 0–1439** (`[min, value]` pairs).
`|null` = absent from Garmin / not enough data — hide it. Errors `400 {detail: str}`.

### A. Stored data (no endpoint of its own)
`IntradayDay` (apps/ingest), one row per athlete-day, filled after each successful sync
(today + yesterday) and by `garmin_backfill_intraday`. Arrays, local time:
`hr [[min, bpm]]` (Garmin's 2-min samples), `stress [[min, 0–100]]` (3-min; Garmin's −1
off-wrist / −2 activity samples are dropped), `body_battery [[min, 0–100]]` (3-min samples,
only the points where the value changes + the last one), `steps [[min, steps, level]]`
(15-min buckets; `level` = `"sleeping"|"sedentary"|"active"|"highly_active"|null`).

### F1 `GET /health/day/?date=` (default today)
`date` in the future or > 365 days ago, or malformed → 400.
```
{ date, is_today: bool, available: bool,           # available=false: no intraday row (all blocks below still present, with nulls/[]/0)
  complete: bool,                                   # the day was fetched after it ended
  fetched_at: datetime|null, data_as_of: "HH:MM"|null,   # last sample time in the arrays
  prev_date: date|null, next_date: date|null,       # next_date null for today
  awake: {start: "HH:MM", end: "HH:MM", source: "sleep"|"steps"|"default"},
  timeline: {
    hr: [[min, int]], stress: [[min, int]], body_battery: [[min, int]],
    steps: [[min, int]],                            # bucket start, steps in that 15 min
    markers: [{type: "run"|"sleep"|"nap"|"habit", start_min: int, end_min: int|null,
               label: str, activity_id: int|null, kind: str|null}] },
  steps: {total: int|null, goal: int|null, goal_source: "garmin"|"adaptive"|null,
          adaptive_goal: int|null, pct: int|null, met: bool|null,
          streak_days: int,                         # consecutive goal days ending this date (or the day before, while today is unmet)
          trend: {last7_avg: int|null, prev7_avg: int|null, change_pct: int|null},
          most_active_hour: Hour|null, least_active_hour: Hour|null,
          hourly: [{hour: int, steps: int}],        # 24 rows
          run_days_avg: int|null, rest_days_avg: int|null, run_days_n: int, rest_days_n: int},
  activity: {sedentary_min: int|null, active_min: int|null, intense_min: int|null,
             sleeping_min: int|null, source: "garmin"|"steps"|null,
             longest_sedentary: {minutes: int, start: "HH:MM", end: "HH:MM"}|null},
  stress: {avg: int|null, max: int|null, rest_min: int, low_min: int, medium_min: int,
           high_min: int, stressful_min: int,       # stressful = medium + high (≥ 51)
           peak: {start: "HH:MM", end: "HH:MM", avg: int}|null,
           stretches: [{start: "HH:MM", end: "HH:MM", minutes: int, avg: int, peak: int}]},
  body_battery: {start: int|null, end: int|null, high: int|null, low: int|null,
                 charged: int|null, drained: int|null, at_wake: int|null,
                 at_bedtime: int|null, now: int|null,
                 events: [{type: "charge"|"drain",
                           cause: "sleep"|"nap"|"run"|"stress"|"rest"|"activity",
                           start: "HH:MM", end: "HH:MM", amount: int,
                           from_value: int, to_value: int}]},
  heart_rate: {resting: int|null, awake_min: int|null, awake_max: int|null,
               awake_avg: int|null,
               trend: {this_week_avg: int|null, prev_week_avg: int|null, change: int|null}},
  score_card: {status: "good"|"ok"|"low"|"no_data", sentence: str,
               bullets: [str], tips: [str]},        # bullets ≤ 3, tips 1–2 (0 when no_data)
  now: {steps: int|null, stress: int|null, stress_at: "HH:MM"|null,
        body_battery: int|null, body_battery_at: "HH:MM"|null} }
Hour = {hour: int, label: "14:00–15:00", steps: int}
```
- Stress bands are Garmin's: rest 0–25, low 26–50, medium 51–75, high 76–100.
  `stretches` = ≥ 30 min at ≥ 51 (gaps ≤ 6 min bridged); `peak` = the 60-min window with
  the highest average stress.
- Steps goal: Garmin's daily goal when set (`goal_source: "garmin"`), else the adaptive
  goal = median of the last 28 days' steps × 1.05, clamped 6,000–15,000 (`"adaptive"`;
  needs ≥ 7 days, else null). `adaptive_goal` is always the adaptive value (or null).
- Activity minutes come from Garmin's daily summary when present (`source: "garmin"`), else
  from the step buckets (< 50 steps / 15 min = sedentary, 50–999 active, ≥ 1000 intense).
  `longest_sedentary` = longest run of < 50-step, not-sleeping buckets while awake.
- `awake`: wake = end of the night that ended this morning, end = start of the next night
  (from sleep data), else from `sleeping` step buckets, else 07:00–23:00.
- Body battery `events`: the biggest charges/drains (≥ 5 points), at most 3 of each,
  labelled by what overlaps them most (sleep, nap, a run, a stressful stretch; charge
  otherwise `rest`, drain otherwise `activity`).
- `heart_rate.awake_*` exclude the night and recorded activities; `trend` = mean daily
  awake average of the 7 days ending this date vs the 7 before.
- Markers: `run` (activity_id, label "Run · 5.2 km"), `sleep` (one per night touching the
  day), `nap` (≥ 30 min of `sleeping` buckets while awake), `habit` (kind
  smoke|alcohol|sugar; `private` only while the Private habit is enabled; `end_min` null).
- Never sent to the AI.

### F2 `GET /health/day/summary/` — Today's compact row
```
{ date, available: bool, steps: int|null, step_goal: int|null,
  goal_source: "garmin"|"adaptive"|null, pct: int|null,
  stress: int|null, stress_at: "HH:MM"|null, body_battery: int|null,
  body_battery_at: "HH:MM"|null, data_as_of: "HH:MM"|null, fetched_at: datetime|null }
```

### F3 `GET /health/day/trends/?range=` (default 4w; 7d|4w|3m|6m|1y)
```
{ range, start, end,
  days: [{date, steps: int|null, step_goal: int|null, active_min: int|null,
          sedentary_min: int|null, stress_avg: int|null, stress_high_min: int|null,
          stressful_min: int|null, awake_hr_avg: int|null, bb_charged: int|null,
          bb_drained: int|null, bb_at_wake: int|null, bb_at_bedtime: int|null}],
  averages: Avg, previous: Avg,
  weeks: [{week_start: date, n: int, steps_avg: int|null, active_min_avg: int|null,
           stress_avg: int|null, awake_hr_avg: int|null}],
  awake_hr_trend: {per_week: float|null, direction: "up"|"down"|"flat"|null, sentence: str},
  weekday_pattern: {by_weekday: [{weekday: 0..6, label: "Mon", n: int,
                                  steps_avg: int|null, stress_avg: int|null}],
                    stress_peak_weekdays: {start: "HH:MM", end: "HH:MM", avg: int}|null,
                    stress_peak_weekends: {start, end, avg}|null,
                    sentence: str|null},
  goal_streak: int,
  day_night_run: {caveat: str,
     groups: [{key: "stress"|"steps", label: str, split: float|null,
               high_label: str, low_label: str, n_high: int, n_low: int,
               rows: [{metric: "sleep_score"|"hrv"|"sleep_h"|"easy_hr"|"efficiency",
                       label: str, unit: str, high: float|null, low: float|null,
                       n_high: int, n_low: int, diff: float|null,
                       enough_data: bool, sentence: str}]}]} }
Avg = {steps, active_min, sedentary_min, stress_avg, stress_high_min, awake_hr_avg,
       bb_at_bedtime: int|null}
```
- `days` oldest first; one row per day in the range with an intraday row (else
  `steps`/`stress_avg` from the daily summary when present). `stress_high_min` = 76–100.
- Weekday pattern needs ≥ 2 days per side for a peak; sentence e.g. "Stress tends to peak
  11:00–12:00 on weekdays."
- Day → night → run: days split at the range median (stress average, then steps);
  "that night" = the sleep that ended the next morning; "next run" = the first run in
  the next 2 days. Sleep/HRV rows need ≥ 5 days each side, run rows ≥ 3 runs each side.
  Association only (`caveat`).

### F4 Compare catalogue (R10 C11) gains group `"day"`
Keys: `active_min` (Active time, min), `sedentary_min` (Sedentary time, min),
`stress_high_min` (High-stress time, min), `bb_bedtime` (Body Battery at bedtime),
`awake_hr` (Awake HR, bpm). Existing keys/groups unchanged (`steps`, `stress` stay
wellness).

### C Reminders: `GET/PATCH /reminders/` gain `nudges`, `quiet_hours`, `data_as_of`
GET body (R10 keys unchanged) adds:
```
nudges: [{key: "move"|"breathing"|"water", label, description, enabled: bool,
          start: "HH:MM", end: "HH:MM", max_per_day: int,
          after_min: int|null,        # move only: 60–90 (default 60)
          threshold: int|null,        # breathing only: 51–90 (default 51)
          every_h: int|null}],        # water only: 1–4 (default 2)
quiet_hours: {start: "HH:MM", end: "HH:MM"},   # default 22:00–07:00
data_as_of: datetime|null,                     # last intraday fetch (UI: "based on your last sync at …")
```
Defaults: all off; move 09:00–19:00, max 4; breathing 09:00–21:00, max 3; water
09:00–21:00, max 6. PATCH accepts `{move|breathing|water: {enabled?, start?, end?,
max_per_day? (1–8), after_min?, threshold?, every_h?}, quiet_hours: {start?, end?}}`
alongside the R10 keys; a field that does not belong to that nudge, or out of range → 400.
- Rules: never inside quiet hours; never during a recorded run or within 60 min after one
  (or while the latest step bucket is `highly_active`); per-day cap; at most one nudge of
  a kind per stretch (dedupe) and ≥ 60 min between two of the same kind (water: `every_h`).
  Move = trailing sedentary stretch ≥ `after_min` in the latest data; breathing = stress
  ≥ `threshold` for ≥ 30 min in the latest data; both only when the latest sample is
  ≤ 60 min old. Water = every `every_h` hours in its window, skipped when water was
  logged within that time or today's target is reached.
- Pushes: move `{title: "Time to move", url: "/health/day"}`, breathing `{title:
  "Breathing break", url: "/health/guides?g=breathing"}`, water `{title: "Drink some
  water", url: "/diet"}`; tags `move`/`breathing`/`water`. No numbers in payloads.

### D Water — `GET/POST /diet/water/`, `DELETE /diet/water/{id}/`
```
WaterDay = {date, target_ml: int, bonus_ml: int, drunk_ml: int, remaining_ml: int,
            pct: int, quick_add: [250, 500],
            logs: [{id, at: datetime, local_date: date, ml: int}]}   # oldest first
```
- `GET /diet/water/?date=` (default today) → WaterDay.
- `POST /diet/water/ {ml: int 50–2000, at?: datetime (default now; ≤ 5 min in the
  future, ≤ 7 days ago)}` → 201 `{log: {id, at, local_date, ml}, day: WaterDay}`.
- `DELETE /diet/water/{id}/` → 200 WaterDay (that log's day).
- `GET /diet/day/` gains `water: WaterDay` (target = the existing water target incl. the
  weather bonus).

### E Run maps
Athlete JSON gains writable `map_hide_endpoints: bool` (default true).

`GET /activities/{id}/route/`
```
{ activity_id: int, available: bool, reason: null|"no_gps"|"too_short",
  hidden_endpoints: bool, trimmed_m: int,             # 200 when hidden, else 0
  total_distance_m: float, sampled_from: int,
  bounds: {south, west, north, east: float}|null,
  start: {lat, lon}|null, finish: {lat, lon}|null,    # first/last point shown (after trimming)
  has_hr: bool, has_elevation: bool, has_segments: bool,
  pace_range: {min: int, max: int}|null,              # 5th–95th percentile s/km, for colouring
  hr_range: {min: int, max: int}|null,
  elevation: {gain_m: float, loss_m: float, min_m: float, max_m: float}|null,
  km_markers: [{km: int, lat, lon, index: int}],      # index into points
  points: [{lat: float, lon: float, dist_m: float, t_s: int,
            pace_s_per_km: int|null, hr: int|null,
            segment: "run"|"walk"|"stop"|null, ele_m: float|null}] }   # ≤ 800
```
- Douglas–Peucker on the GPS track (tolerance grown until ≤ 800 points); pace = smoothed
  over ±15 s at that point (null when slower than 20:00/km or faster than 2:30/km — a GPS jump), HR ±5 s mean, segment from
  the run/walk segmentation. Coordinates rounded to 6 dp. Cached per activity
  (+ segmentation version, + setting).
- `available: false` (`points: []`, nulls) when the activity has no GPS records
  (`no_gps`), or when hiding the ends leaves nothing to draw (`too_short`, a run under
  ~400 m with the setting on).

`GET /activities/routes/?limit=20` (1–50) — "Your routes" overlay
```
{ routes: [{activity_id, date, distance_m: float, points: [[lat, lon]]}] }   # ≤ 150 points each, trimmed like above
```

### R11 backend choices (and where the spec was silent)
- **Garmin methods** (garminconnect 0.3.10, read from the installed package; shapes
  confirmed by one 5-call read-only probe on the dev account): `get_heart_rates(date)`
  (`heartRateValues` [[epoch_ms, bpm|null]], 2-min), `get_stress_data(date)` (same URL as
  `get_all_day_stress`; `stressValuesArray` 3-min with −1/−2 codes **and**
  `bodyBatteryValuesArray` [[epoch_ms, MEASURED|MODELED, level, version]] — so Body
  Battery costs no extra call), `get_steps_data(date)` (96 × 15-min buckets with
  `primaryActivityLevel` sleeping|sedentary|active|highlyActive|generic|none). Not used:
  `get_body_battery` (sparse points + charged/drained — the daily summary already has
  those), `get_body_battery_events` (empty on the dev account), `get_user_summary` /
  `get_stats` (already stored daily in `DailyMetrics.raw["stats"]`: `dailyStepGoal`,
  `sedentarySeconds`, `activeSeconds`, `highlyActiveSeconds`, `bodyBatteryChargedValue` …).
  Local minute-of-day uses Garmin's own offset (`startTimestampLocal − startTimestampGMT`),
  else the athlete's timezone. About 16 KB per stored day.
- **When**: `ingest.sync_intraday_one` is queued 90 s after every successful sync (today +
  yesterday, 6 requests, `GARMIN_SLOW_PAUSE_S` apart, breaker checked before each, first
  429 stops and trips the breaker). Yesterday is marked `complete` when fetched after it
  ended. Nothing is queued after a rate-limited sync.
- **Nudge refresh** (new beat, every 15 min): only for athletes with the move or
  breathing nudge on, a push subscription and Garmin connected, inside those nudge hours
  and outside quiet hours, when today's row is older than `INTRADAY_REFRESH_MIN` (default
  60; 0 = off): today's steps + stress only (2 requests), staggered 60 s apart. Garmin
  data still lags the watch's own phone sync — hence `data_as_of` in the UI.
- **Backfill**: `python manage.py garmin_backfill_intraday --athlete ID | --all [--days 30]
  [--now] [--force]` — days 1..N before today, skipping days already complete, queued in
  7-day chunks 5 minutes apart (athletes one after another); refuses while the breaker is
  open; `--days` capped at 90.
- **Stress stretches** count spells ≥ 51 ("stressful" = Garmin medium + high) because 76+
  spells of 30 min are rare; the High-stress Compare metric is the 76–100 band.
  The weekday peak is the most stressful daytime hour (07–23) averaged over ≥ 2 days,
  widened to a neighbouring hour within 5 points.
- **Body Battery events** are a zig-zag of the series (reversals < 3 points ignored); the
  cause must cover ≥ a third of the leg (min 15 min).
- **Steps total** = the larger of Garmin's daily total and the bucket sum (a nudge
  refresh can be newer than the stored daily summary).
- **Water** lives under `/diet/water/`; `DELETE` returns the updated day (200), not 204.
- **Run maps**: the route is computed from stored per-second records (no Garmin call),
  cached 24 h per activity/segmentation version/setting; `pace_s_per_km` null outside
  2:30–20:00 /km. `GET /activities/routes/` is the optional "Your routes" overlay.
- **Account deletion**: IntradayDay and WaterLog cascade from the Athlete; cached route
  keys are deleted explicitly.
- **Deploy**: migrations `athletes.0009_r11_map_hide_endpoints`, `diet.0002_r11_waterlog`,
  `ingest.0005_r11_intraday`, `reminders.0002_r11_nudges`; restart worker, garmin worker
  and beat (new tasks + beat entry); optional env `INTRADAY_REFRESH_MIN`; then (optional)
  `python manage.py garmin_backfill_intraday --all` once the breaker is clear. No new
  dependency.

## R12 (SPEC_R12.md) — contract for custom ranges + frequency, wake planner and alarms

Conventions as R10/R11 (`/api/`, signed-in, own rows only, `400 {detail}`).

### A. Period parameters (one shared parser, `apps/health/period.py`)
Accepted by: `GET /insights/`, `POST /insights/summary/`, `/health/fitness/`,
`/health/sleep/`, `/health/form/`, `/health/body/`, `/health/day/trends/`,
`/health/compare/`, `GET|POST /habits/summary/`, `/health/training-status/`.
- `range` = a preset: `7d | 4w | 3m | 6m | 1y` (7, 28, 91, 182, 365 days ending today).
  Insights and habits summary also keep their old `12w` (84 days). Defaults unchanged
  (insights 4w, habits 4w, fitness 6m, sleep 4w, form 3m, body 6m, day trends 4w,
  compare 3m, training-status 4w).
- **or** `start=YYYY-MM-DD&end=YYYY-MM-DD` (custom, inclusive). 400 when: both `range`
  and a date are given ("Use either range or start/end dates, not both."); only one of
  start/end; a malformed date; `start > end`; `end` after today; more than 730 days.
- `freq = day | week | month` (optional). Default from the period length: ≤ 92 days →
  `day`, ≤ 366 → `week`, longer → `month`. Anything else → 400.
- Every one of those bodies keeps `range` (the preset, or `"custom"`), `start`, `end`
  and gains
  ```
  period: {start: date, end: date, days: int,
           compare_start: date, compare_end: date,     # the same-length period just before
           freq: "day"|"week"|"month"}
  ```
- **Bucketing** (`analysis/buckets.py`): with `freq=day` every series is exactly as
  before. With `week` / `month`, the series listed below are replaced by one point per
  bucket: `date` = the bucket's first day (Monday / the 1st), the same value keys, plus
  `n: int` (how many daily points went in). Rule per value: **mean** for rates and
  scores, **sum** for counts/amounts, **last** for levels; text fields (e.g.
  `status_key`, `source`) take the last value. Means keep the endpoint's rounding.

| endpoint | bucketed arrays (rule) |
|---|---|
| insights | `hrv.series` (mean), `sleep.series` (mean), `resting_hr.series` (mean), `body_battery.series` (mean), `stress.series` (mean), `respiration.series` (mean), `vo2max.series` (last), `running.run_fraction_trend` / `longest_run_trend` / `easy_pace_trend` (mean) |
| fitness | `vo2max.series`, `fitness_age.series`, `endurance_score.series`, `race_predictions.series`, `lactate_threshold.series` (last) |
| sleep | `nights` stay one per night (unchanged); **new** `series` (below) is bucketed (mean) |
| form | `runs` stay one per run; **new** `series` (below) bucketed (mean; `run_km` sum) |
| body | `series` (last) |
| day/trends | `days` (`steps` sum, the rest mean) — `weeks` unchanged |
| compare | both daily series are bucketed first (sum for `steps`, habits, `run_km`, `training_load`; mean otherwise), then paired; `points[].date` = bucket start; `lag=1` = the next bucket; `n` counts buckets |
| habits summary | `smoke.series`, `alcohol.series`, `sugar.series`, `private.series` (sum of `count`) — `weekly` unchanged |
| training-status | `history` (mean loads, last `status_key`) over the period (was: fixed last 28 days) |

New arrays:
```
sleep.series: [{date, n?: int, sleep_s, need_s, score, deep_s, light_s, rem_s, awake_s,
                restless_moments, spo2_avg, breathing_rate: number|null,
                bedtime_h: float|null, wake_h: float|null}]   # 22.5 = 22:30, 25.0 = 01:00
form.series:  [{date, n?: int, cadence_spm, ground_contact_ms, vertical_oscillation_cm,
                stride_length_m, run_pace_s_per_km: float|null, run_km: float}]
```
(`n` only present when freq ≠ day.) "vs previous" blocks (sleep `previous`, day-trends
`previous`, habits `report`) use `compare_start..compare_end`. Habits summary with a
custom period: amounts, series and report cover start..end; streak, since-quit and
milestones stay "as of today"; the previous label reads "the previous N days".

### B1 Wake planner — `GET /health/wake-plan/?date=` (default tomorrow; today..today+7)
```
{ date, weekday: int (0 = Mon),
  run: {planned: bool, workout_id: int|null, title: str|null, kind: str|null,
        run_time: "HH:MM"|null, run_time_source: "setting"|"history"|null},
  need_s: int, need_source: "garmin"|"default",          # default 8 h
  wake_time: "HH:MM", wake_source: "run"|"habit"|"default",
  bedtime: "HH:MM",                                       # wake − (need + 15 min)
  bedtime_reminder_at: "HH:MM",                           # bedtime − lead (default 30 min)
  my_alarm: Alarm, my_alarm_on_date: "HH:MM"|null,        # the saved alarm if active that day
  watch: Watch,
  flags: [{kind: "watch_alarm_after_run"|"no_watch_alarm_for_run"|
                 "my_alarm_after_run"|"no_alarm_for_run", text: str}],
  android_intent: str,                                    # SET_ALARM intent URL for wake_time
  sentence: str }
```
- Run time: the alarm settings' `run_time`, else the median start time of the last 10
  runs (morning starts only), else none. Wake = run time − 45 min when the plan has a
  non-rest workout that day and a run time is known (`"run"`), else the median wake time
  of the last 7 nights (`"habit"`), else 07:00 (`"default"`). Need = median Garmin sleep
  need of the last 7 nights, else 8 h.
- Flags compare against the run time (only on run days): a watch alarm / my alarm
  active that day but later than run time − 15 min, or none at all ("no_alarm_for_run"
  when neither exists; "no_watch_alarm_for_run" when the watch check is available and
  has none for that day). Text e.g. "Your run is at 06:30 but your watch alarm is 07:00."
- `android_intent` = `intent:#Intent;action=android.intent.action.SET_ALARM;i.android.intent.extra.alarm.HOUR=H;i.android.intent.extra.alarm.MINUTES=M;S.android.intent.extra.alarm.MESSAGE=RunCoach;end`.

### B2 My alarm — `GET/PATCH /alarm/`
```
Alarm = { time: "HH:MM"|null, days: [int 0..6], enabled: bool,
          push: bool,                 # push notification at the alarm time (not a real alarm)
          run_time: "HH:MM"|null,     # "when I usually run", feeds the planner
          bedtime_reminder: bool, bedtime_lead_min: int,   # 15–120, default 30
          push_available: bool,       # VAPID configured
          note: str }                 # "A web app can't set your phone's alarm…"
```
Defaults: time null, days [0..6], enabled false, push false, run_time null,
bedtime_reminder false, lead 30. PATCH any subset; `time`/`run_time` accept null;
`days` = unique ints 0–6 (non-empty when enabled); unknown key / bad value → 400.

### B3 Pushes (R10 web push, every 5 min beat)
- `alarm`: on an alarm day at `time` (when `enabled` and `push`) — title "Alarm",
  body "Time to get up. (A RunCoach notification, not a phone alarm.)", url "/health/sleep".
- `bedtime`: at tomorrow's planned bedtime − lead (when `bedtime_reminder`) — title
  "Wind down", url "/health/sleep". Each at most once per local day, up to 15 min late;
  quiet hours do not apply (the athlete chose these times). No numbers in payloads.

### B4 Watch alarms (read-only) — `GET /health/watch-alarms/`
```
Watch = { available: bool,              # false: no device / the call failed — hide the card
          checked_on: date|null,
          alarms: [{time: "HH:MM", days: [int 0..6], once: bool, enabled: bool,
                    label: str|null, device: str|null}],
          summary: str|null }           # "06:00 Mon–Fri · 08:00 Sat"
```
Fetched once a day with the R10 slow fetch: `get_devices()` then
`get_device_settings(deviceId)` per device (≤ 3), each through the spaced runner and the
breaker; only `alarms` is read. Device settings are never written.

### R12 backend choices (and where the spec was silent)
- **Default freq changes old responses**: with no `freq`, a 6m / 1y preset (fitness and
  body default to 6m) now returns weekly points with `n`. Pass `freq=day` for the R10/R11
  daily series. Week/month buckets are calendar buckets, so the first one can start
  before `start` (its `date` is the Monday / the 1st) and only holds days in the period.
- `1y` (and `7d`, `3m`) are now accepted by insights and habits summary too; `12w` only
  there. `/health/training-status/` gained `range/start/end/period`; its "current" fields
  stay the latest values whatever the period.
- Habits / insights with a custom period: the AI summaries get the same payload (now
  with `period`); the habits previous-period label for custom / 7d / 3m / 1y periods
  reads "the previous N days".
- Compare with week/month: buckets are summed for `steps`, the habits, `run_km` and
  `training_load`, averaged otherwise; the sentence says "Weeks with more …" / "the next
  week"; `MIN_N` (8) applies to buckets.
- **Watch alarms**: `get_device_alarms` exists in 0.3.10 but loops `get_devices` +
  `get_device_settings` internally with no pause, so the slow fetch makes those calls
  itself through the spaced runner (≤ 3 devices). The alarm payload was not probed on a
  live account for R12; parsing accepts `alarmTime` as minutes (or seconds, or "HH:MM"),
  `alarmDays` as full / short weekday names, `DAILY`, `ONCE`, and `alarmMode` ON/OFF.
  A device without an `alarms` key counts as "checked, none set"; no device or a failed
  call → `available: false`.
- Bedtime reminder time comes from tomorrow's wake plan (evening) or, when it falls after
  midnight, today's plan. Alarm / bedtime pushes are evaluated in the existing 5-minute
  `reminders.send_due` beat; no new beat entry.
- **Deploy**: migrations `ingest.0006_r12_watch_alarms`, `reminders.0003_r12_alarm`;
  restart worker, garmin worker and beat. No new env vars or dependencies. Watch alarms
  appear after the next daily slow fetch.

## R13 (SPEC_R13.md) — contract for adaptive plan, race day, injury watch, strength, briefing, reviews, quit support, caffeine, mood, monthly report, export

Conventions as R10–R12: every path is under `/api/`, needs a signed-in athlete (401
otherwise) and only reads/writes the requester's own rows (another athlete's id → 404).
Dates `YYYY-MM-DD`; datetimes ISO 8601 with offset; clock times `"HH:MM"` (24 h, the
athlete's timezone). `|null` = absent / not enough data — hide it. Errors are
`400 {detail: str}` unless noted (DRF field errors `400 {field: [str]}` where a body is
validated by a serializer, as for the Athlete / Race PATCH).

### Athlete JSON (`GET/PATCH /athlete/`) — new fields
```
auto_adjust_plan: bool               # default true. R13 §1 "Auto-adjust plan"
strength_per_week: int               # 0–3, default 0 (writable; else 400)
strength_per_week_suggested: int     # read-only, always 2
caffeine_on_today: bool              # default false — Today quick-log tile for caffeine
pain_daily_check: bool               # default false — ask "Anything hurting?" on Today daily
savings_goal_name: str               # ≤ 60 chars, default "" (e.g. "New shoes")
savings_goal_amount: number|null     # ₹, 1–10,000,000, default null
```
A PATCH that changes `strength_per_week` re-places the future strength sessions (§4); the
response then also carries `strength_reflow: {created, removed}` (else that key is absent).

### Race JSON (`/races/`, `/races/{id}/`) — new writable fields
`goal_time_s: int|null` (600–172800) and `start_time: "HH:MM"|null` (race start; the race
plan assumes 06:30 when null).

### §1 Auto-adjusting plan
```
Adjustment = { id, workout_id: int|null,           # null once the workout is deleted
               workout_date: date, workout_title: str,
               activity_id: int|null,                # the run that triggered it (null for a pain report)
               trigger: "run"|"checkin"|"pain",
               action: "shorten"|"easier"|"run_walk"|"rest"|"swap"|"extend",
               reason: str,                          # plain sentence: why
               chip: str,                            # "Adjusted: shortened to 20 min — your HR ran 8 bpm high yesterday"
               signals: [{key: str, label: str}],    # what fired (keys below)
               before: {title, kind, duration_s, date},
               after:  {title, kind, duration_s, date},
               group: str|null,                      # both rows of one swap share it
               status: "applied"|"undone",
               undoable: bool,                       # applied, workout still planned/future and unchanged since
               created_at, undone_at: datetime|null }
```
- `GET /adjustments/?limit=20` (1–100) → `{enabled: bool, adjustments: [Adjustment]}`
  newest first (the auto changes; the R6 weekly adaptation stays in plan `adjustments`).
- `POST /adjustments/{id}/undo/` → 200 `Adjustment` (status `undone`); the workout gets its
  `before` prescription back, is marked so auto-adjust never touches it again, and the
  watch copy is re-sent when it was on the watch. Undoing one row of a swap undoes both.
  Not undoable (already undone, workout done/past/edited since) → 409 `{detail}`.
- Workout JSON (everywhere: `/calendar/`, `/today/`, `/workouts/{id}/`, plans) gains
  `auto_adjustment: Adjustment|null` (the applied one, if any). `adjusted_by` can now
  also be `"auto"` (changed by auto-adjust) or `"kept"` (the athlete undid one).
- Signal keys: `rpe` (post-run RPE ≥ 8 on an easy session, or ≥ 9), `hr_high` (run HR
  above the session's zone top by ≥ 5 bpm), `hr_drift` (> 8 %), `incomplete` (< 70 % of
  the planned run time), `readiness` (Garmin readiness < 25), `sleep_debt` (≥ 5 h over
  the last 7 nights), `alcohol` (≥ 3 drinks last night), `pain` (pain watch, §3),
  `injury_risk` (injury risk high, §3), `easy_streak` (the +5 % rule).
- Runs: after each run is ingested and segmented (within 2 days of today), again when its
  post-run check-in is saved, and after a pain report. Disabled by `auto_adjust_plan`.

### §2 Race-day planner — `GET /races/{id}/plan/?strategy=even|negative` (default even)
```
{ race: Race, strategy: "even"|"negative", available: bool,
  reason: null|"no_target",                 # no goal and no prediction → splits []
  start_time: "HH:MM", start_time_source: "race"|"default",
  days_to_race: int,
  target: null | {time_s: int, pace_s_per_km: int, source: "goal"|"prediction"|"garmin",
                  goal_time_s: int|null, predicted_time_s: int|null, note: str|null},
  splits: [{km: float, split_s: int, pace_s_per_km: int, elapsed_s: int}],   # last may be partial (e.g. 10.0, 21.1)
  fueling: {duration_s: int|null, carbs_g_per_h: int, fluid_ml_per_h: int,
            electrolytes: bool,
            items: [{at_s: int, at_km: float|null, what: str, amount: str}],   # before, during, after
            notes: [str]},
  weather: null | {date, hour: "HH:MM", temp_c, feels_like_c, humidity, dew_point,
                   precip_prob, wind_kmh: number|null, heat: "cool"|"warm"|"hot"|"very_hot",
                   pace_slowdown_pct: int, advice: [str]},     # only when the race is ≤ 7 days away and a forecast is available
  warmup: [{label: str, duration_s: int, detail: str}],
  taper: {starts_on: date, in_taper: bool,                     # final 10 days
          items: [{key: "sleep"|"carbs"|"kit"|"route"|"bib"|"shoes",
                   label: str, detail: str, due_on: date|null,
                   status: "ok"|"warn"|"todo"|"info"}]},
  morning: [{time: "HH:MM", label: str, detail: str}] }   # wake, breakfast, leave/arrive, warm-up, start
```
404 for another athlete's race. Past races still answer (no weather).

### §3 Injury watch
- `GET /health/injury/` →
```
{ date, risk: "low"|"moderate"|"high",
  flags: [{kind: "ramp"|"long_run_share"|"cadence_drop"|"gct_balance"|"shoe"|"pain",
           level: "watch"|"high", text: str, since: date|null, value: number|null}],
  pains: [Pain],                    # the last 14 days, newest first
  guidance: [str],                  # e.g. "See a physio if it persists" — never a diagnosis
  note: str }                       # what the flags are (plain language)
Pain = {id, date, location: "foot"|"ankle"|"shin"|"calf"|"knee"|"hamstring"|"quad"|"hip"|"lower_back",
        side: "left"|"right"|"both"|"center", severity: 1|2|3, activity_id: int|null,
        note: str, created_at}
```
- `GET /health/pain/?days=30` (1–365) → `[Pain]` newest first.
- `POST /health/pain/ {location, side, severity, date? (default today; ≤ today, ≥ today−14),
  activity_id?, note? (≤ 200)}` → 201 `Pain`; the same date+location+side again updates it
  (200). Bad value → 400. Another athlete's activity_id → 400.
- `DELETE /health/pain/{id}/` → 204.
- Risk: high = any `high` flag or ≥ 3 watch flags; moderate = 1–2 watch flags; else low.
- Morning check-in (`GET /today/`) gains a `pain` reason when the same spot was ≥ 2 on two
  of the last 3 days: `watch` (both 2) or `bad` (a 3) — label "Knee (left) sore 2 days".
  It can only make the verdict easier. `GET /today/` also gains `injury: {risk, flags}`
  and `mood: Mood|null` (§10).

### §4 Strength sessions
```
Strength = { id, date, title: str, duration_s: int (1200), level: int,      # level 1.. (every 2 weeks)
             exercises: [{key: "calf"|"bridge"|"split"|"plank"|"side"|"clam"|"askip"|"hipflexor",
                          name: str, sets: int, reps: int|null, seconds: int|null,
                          per_side: bool, rest_s: int, cue: str}],
             status: "planned"|"completed"|"skipped", completed_activity_id: int|null,
             auto_completed: bool, after_run: bool,          # placed on a run day (after an easy run)
             garmin_status: "none"|"synced"|"changed", garmin_workout_id: int|null,
             can_send_to_watch: bool }
```
- `GET /strength/?start=&end=` (default today−7 … today+28, ≤ 62 days) →
  `{per_week, suggested: 2, can_send_to_watch: bool, sessions: [Strength]}`.
- `PATCH /strength/{id}/ {status?, date?}` → `Strength` (date not in the past).
- `POST /strength/{id}/garmin/` → 202 `{queued: true}` (409 when it cannot be sent:
  not planned, past, Garmin not connected). `DELETE /strength/{id}/garmin/` → 202.
- `/calendar/` day `items` gain `{type: "strength", strength: Strength}`;
  `/calendar/month/` days gain `strength: {id, title, status}|null`.
- A Garmin strength activity on that date marks the session completed (`auto_completed`).

### §6 Morning briefing — `GET /briefing/today/`
```
{ date, ready: bool,                 # false before 04:00 local (then the rest is null/[])
  built_at: datetime|null, dismissed: bool, wake_time: "HH:MM"|null,
  greeting: str,
  readiness: {score: int|null, label: str|null, source: "garmin"|null},
  checkin: {verdict: str, headline: str},
  session: {workout: {id, title, kind, duration_s}|null, adjustment: Adjustment|null,
            strength: {id, title}|null},
  weather: null | {best_window: {start, end, reason}|null, feels_like_max: number|null,
                   heat: str|null, hydration: {before_ml, during_ml_per_h, after_note, electrolytes}|null},
  fuel: null | {kcal: int, carbs_g: int, protein_g: int, water_ml: int},
  focus: {key: str, text: str},
  notes: [{kind: "injury"|"habit"|"sleep"|"mood"|"review", text: str}],
  ai: {status: "none"|"ready", text: str, generated_at: datetime|null} }
```
- `POST /briefing/today/dismiss/` → `{dismissed: true}`.
- `POST /briefing/today/ai/?refresh=1` → `{status, text, generated_at}` (lite tier, cached per
  day; 503 `{detail}` when AI is unavailable / budget used; 429 throttle `chat`). The model
  gets only the briefing's aggregates (no habit counts for the private habit, no notes text
  about pain locations).

### §7 Post-run coach review
- `GET /activities/{id}/review/` (the existing `POST` on this path still opens a chat thread) →
```
{ activity_id, date, available: bool, reason: null|"not_a_run"|"no_metrics",
  kind: str|null,                    # the planned kind, else "EASY"
  bucket: "lt2"|"2to5"|"5to8"|"8plus"|null, compared_with: int,   # similar past runs (0 = none)
  metrics: [{key: "pace"|"hr_at_pace"|"hr_drift"|"cadence"|"run_fraction",
             label, unit, this_run: number|null, typical: number|null,
             delta: number|null, better: bool|null}],
  went_well: [str], to_improve: [str], next_time: [str],
  ai: {status: "none"|"ready", markdown: str, generated_at: datetime|null},
  created_at: datetime|null }
```
- `POST /activities/{id}/review/ai/?refresh=1` → `{status, markdown, generated_at}` (coach tier,
  cached; 503 / 429 as above).
- `GET /reviews/recent/` → `{review: RunReview|null}` — the newest review built in the last
  24 h (the Today card).

### §8 Quit-smoking support
```
Craving = { id, at, local_date, intensity: 1–5, trigger: "coffee"|"alcohol"|"stress"|"after_meal"|
            "boredom"|"social"|"work_break"|"morning"|"other", place: str, mood: int|null (1–5),
            smoked: bool, cigarette_log_id: int|null, note: str, created_at }
```
- `GET /habits/cravings/?days=90` (1–730) → `[Craving]` newest first.
- `POST /habits/cravings/ {intensity, trigger, at?, place? (≤ 60), mood?, smoked? (default
  false), note? (≤ 200)}` → 201 `Craving`. `smoked: true` also logs one cigarette (HabitLog
  smoke at the same time) and links it.
- `PATCH /habits/cravings/{id}/` any of the fields → `Craving` (smoked false→true logs the
  cigarette; true→false deletes the linked one). `DELETE /habits/cravings/{id}/` → 204
  (the linked cigarette log stays).
- `GET /habits/cravings/summary/?range=4w` (R12 period params) →
```
{ range, start, end, period, total: int, resisted: int, resisted_pct: int|null,
  avg_intensity: number|null,
  by_trigger: [{trigger, label, count, resisted}],          # count desc
  by_hour: [{hour: 0..23, count}],
  top_places: [{place, count}],                             # ≤ 5
  peak_hours: [{hour, count}],                              # top 3 hours with ≥ 1
  trend: {this_period: int, previous_period: int, change_pct: int|null,
          direction: "down"|"up"|"flat"|null},
  savings: null | Savings }
Savings = {name, amount, saved: number, remaining: number, pct: int, reached: bool,
           per_day: number|null, eta: date|null}   # money_saved since the quit date (R8)
```
- Achievements gain group `cravings` (`cravings_resisted_1|10|50|100`, unit "cravings").

### §9 Caffeine
- `HabitLog.kind` gains `caffeine` (cups) and every log gains `subtype: "coffee"|"tea"|
  "energy"|"other"|null` (only for caffeine; default `coffee`). `POST /habits/logs/` accepts
  `subtype`. Bulk `DELETE /habits/logs/?kind=caffeine` works. Caffeine is not part of the
  smoke/alcohol/sugar summary, its AI or chat.
- `GET /habits/today/` gains top-level `caffeine: {count: number, last_at: datetime|null,
  on_today: bool}` (`counts` unchanged).
- `GET /habits/caffeine/?range=4w` (R12 period params) →
```
{ range, start, end, period, total: number, per_day_avg: number|null,
  by_type: {coffee, tea, energy, other: number}, late_cutoff: "14:00", late_days: int,
  series: [{date, count: number, late: bool}],
  impact: [{metric: "sleep_score"|"deep_sleep_min"|"awake_min", label, unit,
            late_avg: number|null, other_avg: number|null, diff: number|null,
            n_late: int, n_other: int, direction: "better"|"worse"|"no_clear_difference",
            enough_data: bool, sentence: str}],
  caveat: str }
```
  Late = a caffeine log at or after 14:00 that day; compared with the night that ended next
  morning, vs caffeine-free-after-14:00 days. `enough_data` needs ≥ 4 nights each side.
- Compare catalogue (`/health/compare/metrics/`) gains `caffeine` (group `habits`, cups,
  summed in week/month buckets).

### §10 Mood & energy
```
Mood = {date, mood: 1–5, energy: 1–5, note: str, updated_at}
```
- `GET /mood/?start=&end=` (default the last 30 days, ≤ 366) → `[Mood]` oldest first.
- `POST /mood/ {mood, energy, date? (default today; ≤ today, ≥ today−7), note? (≤ 200)}` →
  201 (created) / 200 (updated) `Mood` — one per day.
- `GET /mood/today/` → `{date, entry: Mood|null}`. `DELETE /mood/{date}/` → 204.
- Compare catalogue gains `mood` and `energy` (group `wellness`, unit "1–5").
- Weekly report gains `mood: {mood_avg, energy_avg, days, previous_mood_avg,
  previous_energy_avg}` (numbers|null, days int). Mood never goes to the AI except these
  averages.

### §11 Monthly report
- `GET /reports/monthly/?month=YYYY-MM` (default last complete month; the current or a future
  month → 400) →
```
{ id, month: "YYYY-MM", start, end, generated_at,
  runs: {count: int, km: number, run_km: number, time_s: int, longest_km: number,
         previous_count: int, previous_km: number, planned: int, planned_done: int},
  prs: [{key, label, display, date}],
  fitness: {vo2max: Change, fitness_age: Change},      # Change = {start: number|null, end: number|null, change: number|null}
  wellness: [{metric: "hrv"|"rhr"|"sleep"|"sleep_score", label, unit, this_month,
              previous_month, delta, better}],
  habits: [{habit: "smoke"|"alcohol"|"sugar"|"caffeine"|"private", label, this_month: number,
            previous_month: number, delta: number, better: bool|null}],
  smoke_free_days: int|null,                            # null when smoking is not tracked
  mood: {mood_avg, energy_avg, days, previous_mood_avg, previous_energy_avg},
  weight: null | {start: number, end: number, change: number},
  injury: {flags: int, pain_days: int},
  went_well: [str], to_improve: [str], goal: str,       # ≤ 3, ≤ 3, 1
  ai: {status: "none"|"ready", markdown: str, generated_at: datetime|null} }
```
- `GET /reports/monthly/list/` → `[{id, month, runs_done, km, generated_at}]` newest first, ≤ 24.
- `POST /reports/monthly/ai/?month=&refresh=1` → `{status, markdown, generated_at}` (coach
  tier; 503 / 429 as weekly). The model gets the report minus the private habit and mood
  notes (averages only).
- Built on the 1st at 06:xx local by an hourly beat (idempotent), or on first read.

### §15 Data export
```
Export = { id, status: "pending"|"running"|"ready"|"failed"|"expired"|"downloaded",
           created_at, finished_at: datetime|null, size_bytes: int|null,
           expires_at: datetime|null,                # ready + 24 h
           download_url: str|null,                   # "/api/export/{id}/download/?token=…" while ready
           error: str }
```
- `POST /export/` → 202 `Export` (built by a Celery task). At most one per hour: 429
  `{detail, retry_after_s}`.
- `GET /export/latest/` → `{export: Export|null}`.
- `GET /export/{id}/download/?token=` → the ZIP (`application/zip`,
  `Content-Disposition: attachment; filename="runcoach-export-YYYY-MM-DD.zip"`). Needs the
  signed-in owner **and** the token; works once (then 410), and not after `expires_at` (410).
  A missing/wrong token → 404. The frontend must fetch it with the Authorization header and
  save the blob (a plain link has no token header). The file is deleted after download or
  expiry.
- ZIP contents: `athlete.json` (settings, no secrets) and CSVs `activities.csv`,
  `laps.csv` (run/walk segments summary), `daily_wellness.csv`, `intraday_daily.csv`,
  `habits.csv`, `cravings.csv`, `mood.csv`, `water.csv`, `meals.csv`, `weights.csv`,
  `plans.csv`, `workouts.csv`, `strength.csv`, `pain.csv`, `reports_weekly.csv`,
  `reports_monthly.csv`, plus `README.txt`.

### Reminders (`GET/PATCH /reminders/`) — two new reminder keys
`morning_briefing` ("Good morning" briefing; time default `06:30` — sent at the wake
planner's wake time for today when it is between 04:00 and 11:00, else at this time) and
`run_reviewed` ("Run reviewed", sent when a post-run review is built; **`time: null`**, a
PATCH with `time` for it → 400). Both off by default. Payloads: `{title: "Good morning",
url: "/", tag: "briefing"}`, `{title: "Run reviewed", url: "/activities/{id}", tag:
"run_review"}` — no numbers.

### R13 backend choices (and where the spec was silent)
- **Auto-adjust storage**: a new `WorkoutAdjustment` model (one row per changed workout,
  with `before`/`after` for Undo), not `PlanAdjustment` — that table's (plan, week_start)
  row is the weekly adaptation's idempotency key. The R6 weekly adaptation is unchanged.
- **Auto-adjust rules** (`planning/adapt.py`, pure). Signal weights: RPE ≥ 9 → 2, RPE 8 on
  an easy session → 1; run HR ≥ 5 bpm over the session's zone top → 1 (≥ 10 → 2); drift
  > 8 % → 1; < 70 % of planned run time → 1 (< 50 % → 2); readiness < 25, sleep debt
  ≥ 5 h / 7 nights, ≥ 3 drinks last night → 1 each; pain watch → 2, pain bad → 4; injury
  risk high → 2. Score 1 = mild: the next session −10 % (a hard one is swapped with a
  later easy day that does not put it the day before a long/hard day, else made easy);
  2–3 = moderate: next −20 % (hard → easy −20 %), the one after −10 %; ≥ 4 = strong: next
  becomes a run/walk at −25 % of total time, the one after −15 %; pain bad → next = rest.
  Window: sessions today … today+4. Never: completed/skipped/past, RACE, WALK/REST,
  moved (`moved_from`), check-in applied, `adjusted_by="kept"` (an undo) or already auto
  (except an auto *extension*, which is reverted before easing). The same run / pain is
  acted on once: re-evaluating it changes more sessions only when a new signal key appears.
- **+5 % rule**: only with no strain signal, readiness ≥ 50 (or unknown), no pain, injury
  risk low, and the last 3 runs all planned EASY/RUN_WALK/LONG sessions with ≥ 90 % of the
  planned run time, RPE ≤ 6 (or none), HR not over the zone top, drift ≤ 5 %. Target: the
  next EASY/RUN_WALK session; extra = min(5 % of its running, the room left in its plan
  week) in whole minutes, ≥ 1 min. "Room" = the week's run seconds as the plan prescribed
  them before any auto change (skipped and RACE excluded) minus what is prescribed now —
  so the week can never exceed the plan's own volume (in practice the rule only gives back
  time an earlier auto change took). Plan week = 7-day blocks from the first phase start.
- **When it runs**: `planning.after_run` (queued after `activities.derive_one` for an
  activity dated today or the 2 days before — history re-derivations never trigger it),
  `planning.after_checkin` (post-run check-in saved; RPE), `planning.after_pain` (pain
  report). Changed workouts on the watch are re-sent via `garmin_sync.resync_on_garmin`.
- **Pain** in the morning check-in: a sore spot (≥ 2) on two of the last 3 days adds
  reason `pain` (`watch`, or `bad` with a 3). A pain `watch` alone now makes the verdict at
  least `easy`; `bad` → `rest` (existing rule). The check-in AI explanation gets the label
  "Pain reported" — body locations never go to a model.
- **GCT balance**: read from the FIT session message `avg_stance_time_balance` into
  `ActivityMetrics.gct_balance_left_pct` (30–70 % only). Existing activities get it only
  after re-derivation (`python manage.py derive` / an algorithm bump).
- **Injury flags in the monthly report**: `flags` = spots with ≥ 2/3 on two or more days
  that month; `pain_days` = days with any report (flags are not replayed day by day).
- **Strength → watch**: supported. garminconnect 0.3.10 has
  `Garmin.upload_strength_workout(StrengthWorkout)` (→ `upload_workout`, POST
  /workout-service/workout) and the exercise catalogue `garminconnect.exercises`; the
  session is uploaded with `StrengthWorkout.model_validate(payload)` then
  `schedule_workout`, on the garmin queue with the shared breaker and the existing client
  (`apps/planning/garmin_strength_push.py`). The 8 Guides exercises map to catalogue pairs
  (calf → CALF_RAISE/STANDING_CALF_RAISE, bridge → HIP_RAISE/HIP_RAISE, split squat →
  LUNGE/LUNGE, plank → PLANK/PLANK, side plank → PLANK/SIDE_PLANK, clamshell →
  HIP_STABILITY/HIP_STABILITY, A-skip → WARM_UP/WALKING_HIGH_KNEES, hip-flexor →
  WARM_UP/STRETCH_LUNGING_HIP_FLEXOR), verified against the installed catalogue in tests.
  Holds end on time, the rest on reps (per-side doses doubled). Not probed on a live
  account. `can_send_to_watch` = Garmin connected.
- **Strength placement** needs an active plan; sessions are placed up to 8 weeks ahead
  (nightly top-up `planning.strength_topup`), never in the 5 days before the race, and
  re-placed when `strength_per_week`, the training days or runs per week change, or a plan
  is accepted. A day in the past or a completed/skipped session is never moved.
- **Run review URL**: `GET /activities/{id}/review/` shares its path with the R6 `POST`
  (open a chat thread) — the POST still works and is the only one throttled.
- **Caffeine** is a `HabitLog` kind with its own report (`/habits/caffeine/`, late-vs-not
  rows in the R9 row shape) rather than a fourth habit inside `/habits/summary/` — adding
  it there would have changed the smoke/alcohol/sugar summary, its AI input and the chat
  tool. Garmin has no sleep-latency figure; "awake time in the night" stands in (said in
  `caveat`). The monthly report lists caffeine with the other habits.
- **Mood**: the weekly report gains a `mood` averages block (computed on read); mood notes
  never leave the database (export aside).
- **Briefing** is recomputed on each read after 04:00 and stored once a day (dismissal, AI
  text). The 15-minute beat builds it at the wake planner's wake time (04:00–11:00, else
  06:30); the `morning_briefing` push is sent at that time too.
- **Export token** = HMAC-SHA256 (SECRET_KEY) of the export id and creation time —
  re-derivable, never stored. The download needs the owner's auth and the token; the ZIP is
  unlinked as soon as it is opened for the download. One export per hour per athlete
  (any status). Includes everything the athlete owns, the private habit too; excludes FIT
  files, meal photos and Garmin tokens. The DEBUG media route now refuses `exports/` (also
  after `..` normalisation).
- **Account deletion**: all R13 tables cascade from the Athlete; `media/exports/athlete_<id>/`
  is removed with the other files.
- **Deploy**: migrations `athletes.0010_r13`, `activities.0006_r13_gct_review`,
  `coaching.0008_r13_ai_kinds`, `habits.0003_r13_caffeine_cravings`, `health.0002_r13`,
  `planning.0005_r13`, `reminders.0004_r13_briefing_review`. Restart worker, garmin
  worker and beat (new tasks: planning.after_run / after_checkin / after_pain /
  garmin_strength_push (garmin queue) / strength_topup, health.monthly_reports /
  build_monthly_report / morning_briefings, athletes.build_export / export_cleanup; new
  beat entries monthly-reports, morning-briefings, strength-topup, export-cleanup). New
  AI tier names `morning_briefing` (lite), `run_review`, `monthly_report` (coach) — no new
  env vars, no new dependencies. Off-site backups: deploy/RESTORE.md.

## R14 (SPEC_R14.md) — contract for Today layout, weather report + smart reschedule, calendar feed, experiments, goals, heart adaptation, admin + Gemini

Conventions as R10–R13: every path is under `/api/`, needs a signed-in athlete (401
otherwise) and only reads/writes the requester's own rows (another athlete's id → 404).
Dates `YYYY-MM-DD`; datetimes ISO 8601 with offset; local clock times `"HH:MM"`; hourly
weather times are local `"YYYY-MM-DDTHH:MM"` (as `/weather/today/`). `|null` = absent / not
enough data — hide it. Errors `400 {detail: str}` unless noted (DRF field errors
`400 {field: [str]}` on the Athlete PATCH). Pace = seconds per km; speeds in m/s;
temperatures °C; money from the AI log in **USD** (`*_usd`), GCP credit in **INR**.
Exceptions to the auth rule: `GET /cal/{token}.ics` (token only) and `/admin/…` (staff only).

### §1 Athlete JSON (`GET/PATCH /athlete/`) — new fields
```
today_layout: [str] | null       # ordered keys of the optional Today cards that are ON;
                                 # null = the app's default layout. Writable. Each key
                                 # matches ^[a-z][a-z0-9_]{0,31}$, unique, ≤ 30 keys
                                 # (else 400 {today_layout: [...]}). The backend does not
                                 # own the card catalogue — unknown keys are stored as-is.
weather_auto_apply: bool         # default false — "Auto-apply weather swaps" (§3)
```

### §3 Weather report — `GET /weather/report/` (always 200)
```
{ available: bool, reason: null|"no_location"|"unavailable",
  location_name: str|null, source: "runs"|"city"|"none", generated_at: datetime,
  now: null | {time, temp, feels_like, humidity, dew_point, wind (km/h), uv,
               weather_code, condition: str|null,
               aqi: number|null, pm25: number|null,
               aqi_level: "good"|"moderate"|"sensitive"|"unhealthy"|"very_unhealthy"|"hazardous"|null,
               aqi_meaning: str|null,            # plain words, e.g. "Unhealthy for sensitive groups — keep runs easy"
               uv_level: "low"|"moderate"|"high"|"very_high"|"extreme"|null},
  hourly: [Hour],                                # next 48 h from the current hour
  best_windows: [{date, start, end, reason, feels_like: number|null, aqi: number|null}],
                                                 # ≤ 1 per local day in the 48 h, coolest/cleanest
                                                 # slot starting 05–08 or 17–19 local, from now on
  daily: [Day],                                  # 7 days from today
  sun: {sunrise: "HH:MM"|null, sunset: "HH:MM"|null},     # today
  heat: "cool"|"warm"|"hot"|"very_hot"|null, pace_slowdown_pct: int,
  advisories: [{level: "info"|"caution"|"warning", text}],
  hydration: {before_ml, during_ml_per_h, after_note, electrolytes} | null,
  food: [str], daily_water_bonus_ml: int,        # same rules as /weather/today/
  runs: [RunVsWeather],                          # planned runs today … today+6
  suggestions: [WeatherSuggestion] }             # pending ones (same as §3 list below)
Hour = {time, temp, feels_like, humidity, dew_point, precip_prob, wind, uv, weather_code,
        condition, aqi, pm25, run: "good"|"ok"|"poor"|"bad"|null, best: bool}
        # run: bad = thunder, rain ≥ 70 %, AQI > 150 or feels-like ≥ 34; poor = feels ≥ 30,
        # rain ≥ 40 % or AQI > 100; ok = feels ≥ 26 or AQI > 50; else good. best = inside a best window.
Day = {date, temp_min, temp_max, feels_like_max, precip_prob_max: int|null,
       precip_mm: number|null, weather_code, condition, uv_max, aqi_max: number|null,
       sunrise: "HH:MM"|null, sunset: "HH:MM"|null,
       run_verdict: "good"|"caution"|"bad"|null,   # bad = no candidate window (05–08, 17–19) is runnable
       reasons: [str]}
RunVsWeather = {date, workout_id, title, kind, duration_s, verdict: "good"|"caution"|"bad"|null,
                reasons: [str], best_window: {start, end, reason}|null,
                suggestion_id: int|null}
```
Unavailable → `now`, `heat`, `hydration` null, lists empty, bonus 0 (as `/weather/today/`).
Open-Meteo forecast (7 days) + air quality (5 days; AQI null beyond), cached per rounded
place per hour. Reading the report also runs the reschedule check (idempotent).

### §3 Weather-smart reschedule
```
WeatherSuggestion = {
  id, workout_id: int|null, workout_title: str, workout_kind: str, duration_s: int,
  from_date: date, to_date: date,
  action: "move"|"swap",                 # swap: the target day's optional walk goes to from_date
  swap_with: {workout_id, title, kind}|null,
  text: str,                             # "Weather: move Thu run to Fri?"
  reason: str,                           # "Thu: feels like 35 °C even at 06:00; Fri morning 29 °C."
  reasons: [{key: "heat"|"storm"|"rain"|"air", text: str}],
  from_weather: DayBrief, to_weather: DayBrief,
  status: "pending"|"applied"|"dismissed"|"expired",
  auto_applied: bool, created_at, decided_at: datetime|null }
DayBrief = {date, best_feels_like: number|null, precip_prob_max: int|null,
            aqi_max: number|null, condition: str|null, verdict: "good"|"caution"|"bad"}
```
- `GET /plan/weather-suggestions/?status=pending|all` (default pending) →
  `{auto_apply: bool, suggestions: [WeatherSuggestion]}` newest first (`all`: last 30 days).
- `POST /plan/weather-suggestions/{id}/apply/` → 200 `WeatherSuggestion` (status applied).
  409 `{detail}` when it no longer holds (not pending, workout moved/done/edited, from_date is
  today or past, target day now taken, spacing broken). The watch copy is re-sent.
- `POST /plan/weather-suggestions/{id}/dismiss/` → 200 (status dismissed; that workout on
  that date is never suggested again). 409 when not pending.
- `POST /plan/weather-suggestions/check/` → 200 `{created: int, suggestions: [...]}` (runs the
  check now; also runs on `GET /weather/report/` and daily at 18:xx local).
- Rules: planned runs (EASY, RUN_WALK, LONG, TEMPO, INTERVALS; never RACE/WALK/REST) dated
  today+1 … today+3, not completed/skipped. A day is bad when every candidate window
  (05–08, 17–19 local) has feels-like ≥ 34 °C, a thunderstorm or rain ≥ 70 %, or AQI > 150.
  Target = an available training day in the same Mon–Sun week, after today, on or before
  the day before the race, with no planned run (an optional WALK there is swapped), with
  a runnable window that scores better. Spacing: a LONG/TEMPO/INTERVALS session never lands
  next to another LONG/hard/race day; no run lands on the day before a race. The session's
  content never changes (moving never makes it harder). With `weather_auto_apply` on, the
  suggestion is applied at once (`auto_applied: true`); otherwise nothing moves until Move.
  Pending suggestions expire when from_date is today or past or the workout changed.

### §5 Calendar feed (ICS)
```
CalendarFeed = { enabled: bool, url: str|null,        # "https://<host>/api/cal/<token>.ics"
                 webcal_url: str|null,                  # same with webcal://
                 google_url: str|null,                  # https://calendar.google.com/calendar/r?cid=<webcal url, encoded>
                 path: str|null,                        # "/api/cal/<token>.ics" (build your own origin)
                 created_at: datetime|null, last_fetched_at: datetime|null }
```
- `GET /calendar-feed/` → `CalendarFeed` (`enabled: false`, nulls before one is made).
- `POST /calendar-feed/` → 201 `CalendarFeed` — creates it, or **regenerates** the token (the
  old URL stops working at once).
- `DELETE /calendar-feed/` → 204 (revoked; the URL 404s).
- `GET /cal/{token}.ics` — **no auth header**; unknown/revoked token → 404. `text/calendar;
  charset=utf-8`, `ETag`, `Last-Modified`, `Cache-Control: private, max-age=900`;
  `If-None-Match` / `If-Modified-Since` → 304. Contents: planned/completed workouts of the
  active plan (today−30 … today+180), planned/completed strength sessions, and races.
  Workouts and strength are all-day events (no time of day exists); a race with
  `start_time` is a timed event in UTC (`…Z`). `UID` stable per item
  (`workout-<id>@runcoach`, `strength-<id>@runcoach`, `race-<id>@runcoach`); `SEQUENCE`
  increases each time an item's date/title/steps change. Titles like
  "🏃 Easy run · 30 min"; DESCRIPTION = the steps ("Walk warm-up 2 min", "Run 4:30 easy
  (HR 130–145)", …) and purpose. No location, no health data.

### §7 Self-experiments
```
Experiment = { id, kind: "no_alcohol"|"no_late_caffeine"|"no_sugar"|"smoke_free"|"bed_by"|"steps"|"custom",
               title: str, start: date, end: date, days: int (7–42),
               rule: Rule, status: "scheduled"|"active"|"completed"|"stopped",
               decision: "keep"|"stop"|null, created_at, ended_at: datetime|null,
               progress: {day: int, days: int, pct: int},            # day 0 before it starts
               adherence: {days_counted: int, days_kept: int, pct: int|null,
                           today: bool|null,                         # null = not known yet
                           series: [{date, kept: bool|null, value: number|null}]},
               chip: str }                                           # "No alcohol · day 9/21 · 8 of 9 days kept"
Rule = {habit?: "alcohol"|"caffeine"|"sugar"|"smoke"|"private", max_per_day?: number,
        after?: "HH:MM",       # caffeine: counts only logs at/after this time
        bedtime?: "HH:MM",     # bed_by: sleep start at or before this (from Garmin sleep)
        min_steps?: int}       # steps
```
- `GET /experiments/templates/` → `[{kind, title, description, rule, default_days, source:
  "habits"|"caffeine"|"sleep"|"steps"}]` (custom: rule `{habit: "alcohol", max_per_day: 0}` to edit).
- `GET /experiments/?status=active|scheduled|completed|stopped|all` (default all) → `[Experiment]`
  newest first.
- `POST /experiments/ {kind, days? (7–42, default template), start? (today … today+14,
  default today), title? (≤ 80), rule? (custom: {habit, max_per_day 0–50}; bed_by:
  {bedtime}; steps: {min_steps 1000–50000}; others fixed)}` → 201 `Experiment`. One
  scheduled/active experiment at a time → 409 `{detail}`. Private habit allowed only when
  `private_habit_enabled` (label stays "Private").
- `GET /experiments/{id}/` → `Experiment` + `result: Result`.
- `PATCH /experiments/{id}/ {title?, decision?: "keep"|"stop"|null}` → `Experiment`.
- `POST /experiments/{id}/stop/` → `Experiment` (status stopped, end = yesterday or start).
- `DELETE /experiments/{id}/` → 204.
- `GET /experiments/active/` → `{experiment: Experiment|null}` (the Today chip: active one, else a
  completed one with `decision: null` that ended in the last 7 days).
```
Result = { final: bool,                         # false while running ("so far")
           baseline: {start, end}, during: {start, end},
           adherence_pct: int|null,
           metrics: [{key: "hrv"|"rhr"|"sleep_score"|"stress"|"easy_hr"|"mood"|"energy",
                      label, unit, before: number|null, during: number|null,
                      diff: number|null, n_before: int, n_during: int,
                      higher_is_better: bool, enough_data: bool,           # n ≥ 4 each side (easy_hr: ≥ 2 runs)
                      direction: "better"|"worse"|"no_clear_difference"|null,
                      sentence: str}],
           summary: str, caveat: str,          # non-causal wording
           share: {title: str, lines: [str]} } # share card text (no private-habit name)
```
Baseline = the same number of days right before `start`. Kept = the day's logs meet the rule
(habit days with no log count as kept once the day is over; bed_by/steps days without Garmin
data are `null`, not counted).

### §8 Long-term goals
```
Goal = { id, kind: "race_time"|"distance"|"weight"|"smoke_free_days"|"vo2max"|"resting_hr"|"weekly_km"|"custom",
         title: str, unit: str,                # s | km | kg | days | ml/kg/min | bpm | free text
         target: number, target_date: date|null,
         start_value: number|null, start_date: date,
         distance_km: number|null,             # race_time only: 5 | 10 | 21.1 | 42.2
         direction: "up"|"down",               # from start → target
         current: number|null, current_as_of: date|null, current_source: str|null,
         progress_pct: int|null,               # 0–100
         status: "active"|"achieved"|"abandoned", achieved_on: date|null,
         milestones: [{pct: 25|50|75|100, value: number, reached_on: date|null}],
         projection: {date: date|null, method: "trend"|null, label: "estimate",
                      on_track: bool|null,     # vs target_date (null without one)
                      note: str},
         series: [{date, value}],              # ≤ 120 points, oldest first
         display: {target: str, current: str|null, start: str|null},   # "52:30", "68.4 kg"
         chip: str, created_at }
```
- Current value: race_time = Garmin race prediction for that distance (`current_source:
  "garmin_prediction"`); distance = longest single run (km) since start; weight = latest
  weight entry; smoke_free_days = current smoke-free streak; vo2max = latest Garmin VO2max;
  resting_hr = 7-day median resting HR; weekly_km = last 7 days' run+walk km of runs;
  custom = latest value posted below.
- `GET /goals/?status=active|achieved|abandoned|all` (default active) → `[Goal]`.
- `POST /goals/ {kind, target, target_date? (> today), title? (≤ 80), distance_km? (race_time,
  required), unit? (custom, ≤ 12), start_value? (custom required; else taken from data, and
  required when there is no data yet)}` → 201 `Goal`. Max 10 active → 409.
- `GET /goals/{id}/`, `PATCH /goals/{id}/ {title?, target?, target_date?, status?: "active"|"abandoned"}`,
  `DELETE /goals/{id}/` → 204.
- `POST /goals/{id}/values/ {value, date? (≤ today)}` → 201 `Goal` (custom only; else 400).
- `GET /goals/chip/` → `{goal: Goal|null, text: str|null}` — the active goal closest to done.
- Reaching 25/50/75/100 % stores a badge (Achievement key `goal_<id>_<pct>`, label "Goal 50%:
  <title>") so it shows in `/achievements/` recent; 100 % sets status achieved.
- Projection: least-squares line over the last 60 days of `series` (≥ 3 points over ≥ 14 days),
  moving towards the target → the date it crosses (≤ 3 years), else `date: null` with a note.

### §9 Heart adaptation — `GET /health/heart/?range=` (R12 period params; default 3m; also `all`)
Optional `ref_hr` (100–200; default the athlete's `hr_ceiling` − 5, i.e. 150 at the default
ceiling) and `ref_pace` (s/km 180–1200; default the middle of the easy band). 400 otherwise.
```
{ range, start, end, ref_hr: int, ref_hr_band: 3, ref_pace_s_per_km: int, ref_pace_band_s: 15,
  hot_threshold_c: 28,
  runs: [HeartRun],                                    # oldest first, runs in the range
  trend: [{date, activity_id, hr_at_ref_pace, pace_at_ref_hr, efficiency, decoupling_pct,
           duration_under_cap_s}],                     # rolling median of the last 7 runs (≥ 3)
  trend_cool: [same],                                  # hot runs left out (the hot-day toggle)
  since_day1: null | {first: Snapshot, latest: Snapshot, sentences: [str]},
  heat: {hot_runs: int, cool_runs: int, unknown_runs: int,
         hot_vs_cool: null | {metric: "hr_at_ref_pace", hot_avg, cool_avg, diff, n_hot, n_cool},
         adaptation: null | {early_hot_avg, recent_hot_avg, diff, n_early, n_recent},
         sentence: str|null},
  headline: str,                                       # "Now 11 min at ≤150 bpm (day 1: 5 min)."
  sentences: [str],
  key_numbers: [{key: "duration_under_cap"|"hr_at_ref_pace"|"pace_at_ref_hr"|"decoupling",
                 label, value: number|null, unit, display: str|null,
                 change: number|null,                  # latest 7-run median vs first 3 runs
                 better: bool|null, info: str}],       # info = the (i) text
  weather_pending: bool,                               # run weather still being fetched
  caveat: str }
HeartRun = { activity_id, date, started_at, distance_km, run_s, steady_s,
             hr_at_ref_pace: int|null, hr_at_ref_pace_adj: int|null,     # adj = heat-normalised
             pace_at_ref_hr: int|null, efficiency: number|null, efficiency_adj: number|null,
             decoupling_pct: number|null, hr_recovery_bpm: int|null,
             hr_recovery_end_bpm: int|null, settle_s: int|null,
             duration_under_cap_s: int, feels_like_c: number|null,
             hot: bool|null, elev_gain_per_km: number|null, hilly: bool,
             flags: [str] }                                # "hot" | "hilly" | "short" | "no_hr"
Snapshot = {date, runs: int, duration_under_cap_s: int|null, hr_at_ref_pace: int|null,
            pace_at_ref_hr: int|null, efficiency: number|null}
```
`efficiency` = metres per minute per bpm over steady running (higher = more speed per beat).
`since_day1` uses all history: first = median of the first 3 runs, latest = of the last 3.

### §14 Admin (staff only: `is_staff`; everyone else 403, signed-out 401)
The session `user` object (`GET /auth/me/`, login and register responses) gains
`is_staff: bool` — show the Admin entry only when true. (`POST /auth/refresh/` returns
only `{access}`, unchanged.)

All under `/api/admin/`. Never returns keys or secrets — only `configured: bool`.
```
AdminUser = { id, username, display_name, email, joined: datetime, last_active: datetime|null,
              is_active: bool, is_staff: bool, garmin_connected: bool,
              garmin_last_sync: datetime|null,
              plan: {id, name, race_date: date|null}|null,
              ai: {calls_month: int, cost_month_usd: number, budget: int,
                   budget_source: "default"|"custom"} }
Invite = {id, code, note, max_uses, uses, expires_at|null, created_at, usable: bool, revoked: bool}
```
- `GET /admin/users/` → `{registration_mode: "open"|"invite"|"closed", default_budget: int,
  users: [AdminUser]}` (newest first).
- `PATCH /admin/users/{id}/ {is_active?: bool, ai_budget?: int|null (0–100000; null = default)}`
  → `AdminUser`. Disabling also signs the user out everywhere. Your own account → 400.
- `GET /admin/invites/` → `[Invite]`; `POST /admin/invites/ {note? (≤ 200), max_uses? (1–100,
  default 1), expires_in_days? (1–365|null)}` → 201 `Invite`; `POST /admin/invites/{id}/revoke/`
  → 200 `Invite` (kept, unusable).
- `GET /admin/ai/providers/` → `[{key: "openai"|"gemini", label, configured: bool,
  base_url: str|null, features: {tools: bool, json_schema: bool, streaming: bool, vision: bool},
  models: [str]}]` (models = the price table rows for that provider).
- `GET /admin/ai/config/` → `{tiers: [Tier], operations: {operation: tier}}`
  `Tier = {tier: "lite"|"fast"|"coach"|"deep", provider, model, source: "db"|"env",
  env_provider, env_model, available: bool, updated_at: datetime|null}`.
- `PUT /admin/ai/config/ {tiers: [{tier, provider, model} | {tier, reset: true}]}` → same body.
  Provider must be configured and the model in its price table (else 400).
- `POST /admin/ai/test/ {provider, model, prompt (1–2000 chars), json?: bool}` →
  `{ok: bool, text: str, json: object|null, latency_ms, input_tokens, output_tokens,
  cost_usd, error: str|null}` (logged as operation `admin_test`, no budget).
- `GET /admin/ai/prices/` → `[{id, provider, model, input_per_m_usd, output_per_m_usd, note,
  updated_at}]`; `POST /admin/ai/prices/` (same fields) → 201; `PATCH /admin/ai/prices/{id}/`;
  `DELETE /admin/ai/prices/{id}/` → 204 (409 while a tier uses it).
- `GET /admin/ai/stats/?range=7d|4w|3m|6m|1y` (default 4w) →
```
{ range, start, end,
  totals: {calls, ok, errors, refused, cached: 0, error_rate: number (0–1), input_tokens,
           output_tokens, cost_usd, avg_latency_ms: int|null},
  month: {start, calls, cost_usd, input_tokens, output_tokens},     # calendar month to date (UTC)
  by_day: [{date, calls, errors, input_tokens, output_tokens, cost_usd}],   # every day in range
  by_month: [{month: "YYYY-MM", calls, errors, input_tokens, output_tokens, cost_usd}],  # last 12
  by_tier: [{tier, calls, errors, input_tokens, output_tokens, cost_usd}],
  by_operation: [{operation, tier, calls, errors, input_tokens, output_tokens, cost_usd}],
  by_user: [{athlete_id: int|null, name: str, calls, errors, input_tokens, output_tokens, cost_usd}],
  by_model: [{provider, model, calls, errors, input_tokens, output_tokens, cost_usd, avg_latency_ms}],
  recent_errors: [{at, operation, provider, model, status, error}] }   # ≤ 20, error ≤ 200 chars
```
- `GET /admin/system/` →
```
{ version: {git_sha: str|null, image: str|null, source: "env"|"kubernetes"|null},
  garmin: {breaker_open: bool, reason: str|null, retry_after_s: int|null,
           users: [{athlete_id, name, connected, last_sync: datetime|null,
                    hours_since_sync: number|null, backfilled: bool}]},
  celery: {available: bool, queues: [{name, length: int}]},
  backups: {available: bool, reason: str|null, schedule: str|null,
            last_success_at: datetime|null, last_schedule_at: datetime|null,
            jobs: [{name, status: "succeeded"|"failed"|"running", started_at, finished_at}],
            r2: {configured: bool|null, note: str}},
  kubernetes: {available: bool, reason: null|"not_in_cluster"|"forbidden"|"error",
               nodes: [{name, ready: bool, cpu_cores: number, cpu_used_cores: number|null,
                        cpu_pct: int|null, memory_bytes: int, memory_used_bytes: int|null,
                        memory_pct: int|null, disk_bytes: int|null,
                        disk_allocatable_bytes: int|null}],
               pods: [{name, app: str|null, phase, ready: bool, restarts: int,
                       started_at: datetime|null, node: str|null}]},
  gcp: {configured: bool, trial_end: date|null, days_left: int|null, credit_inr: number|null},
  checked_at: datetime }
```

### R14 backend choices (and where the spec was silent)
- **Contract details added after the first commit** (additive only): experiment
  `adherence.series[]` items also carry `display: str|null` ("23:10", "8,412 steps",
  "2 drinks"); for `bed_by` the numeric `value` is minutes after 12:00 noon (so 23:30 = 690,
  00:30 = 750). Admin `by_user` rows with `athlete_id: null` are the admin's own test prompts
  (`name: "Admin tests"`).
- **ICS path** is `/api/cal/<token>.ics` (not `/cal/…`): it then goes through the existing
  ingress route and the PWA service worker's `/api` deny-list with no deploy change. The
  token is `secrets.token_urlsafe(32)` (256 bits), stored as-is (it is a capability URL the
  athlete must be able to copy again); regenerate replaces it, DELETE revokes it.
  `DTSTAMP` = the feed's last change (so identical content gives an identical body and
  ETag). Events: workouts of the active plan (RACE-kind workouts are left out — the Race
  itself is the event), strength sessions, races. All-day events are `TRANSP:TRANSPARENT`.
- **Weather swap**: a day is "bad" only when every candidate start hour (05–08, 17–19) is
  bad, so a hot afternoon with a cool morning never triggers a move. "Better" = the
  target's best window rates good/caution and scores lower (feels-like + AQI and rain
  penalties). Moves stay inside the session's Mon–Sun week, on an available training day
  with no other run, never after the day before the race; LONG/TEMPO/INTERVALS never next
  to another LONG/hard/race day. `moved_from` keeps the original date (as a manual move);
  the watch copy is re-sent through `garmin_sync.resync_on_garmin`. A dismissed (or
  applied) suggestion is never re-proposed for the same workout + date. The daily check is
  the beat `weather-checks` (hourly, acts at 18:xx local); reading `/weather/report/`
  also checks. Pending suggestions expire when their day arrives or the workout changes.
- **Weather report** uses separate 7-day forecast / 5-day air-quality cache keys (`fc7`,
  `aq5`) next to the existing 2-day ones, so `/weather/today/` is unchanged.
- **Experiments**: one scheduled/active experiment at a time. A habit day with no log
  counts as kept once the day is over; today is `null` until it can no longer change
  (a logged drink → false; steps reached → true). Bedtime = Garmin `sleep_start_local`,
  the night belonging to the evening it started (00:40 belongs to the day before). Nightly
  numbers (HRV, resting HR, sleep score) are moved back one day — the morning after a rule
  day is "during". Easy-run HR = average run-block HR of runs ≥ 10 min whose run pace is
  within the easy band (−20 s … +60 s/km). Thresholds for "clear difference": HRV 3 ms,
  RHR 2 bpm, sleep score 3, stress 3, easy HR 3 bpm, mood/energy 0.4; n ≥ 4 days each
  side (easy HR ≥ 2 runs). The private habit is allowed in a custom experiment (no AI is
  involved); its share card says "Private habit limit".
- **Goals**: `distance` = longest single run (km); `weekly_km` = the last 7 days of runs;
  `resting_hr` = 7-day median; `smoke_free_days` = the current streak of finished days.
  Start value defaults to the current value (distance: the longest run of the last 30
  days). Milestone badges are stored as Achievement rows (`goal_<id>_<pct>`), so they show
  in `/achievements/` `recent`; the badge grid itself is unchanged. 100 % sets `achieved`.
- **Heart adaptation** (`analysis/heart_adaptation.py`, definitions in its docstring):
  steady running = 30-s windows in run blocks after the first 5 min of the activity and
  the first 60 s of each block, speed CV ≤ 12 %, ≥ 80 % HR coverage, ≥ 1.4 m/s. Reference
  bands ±15 s/km and ±3 bpm with ≥ 2 min matched. Efficiency in m/min per bpm; terrain
  adjustment +8 m per metre climbed (smoothed altitude); heat adjustment −1 bpm per °C of
  feels-like above 20 °C; hot ≥ 28 °C; hilly ≥ 15 m/km. Per-run numbers are cached in
  `RunHeartStats` (key = algorithm + segmentation version + references + feels-like).
  Weather at run start comes from the Open-Meteo **archive** (older than 6 days) or the
  forecast API's `past_days` (recent), per rounded start position (2 dp) — filled by the
  `health.heart_weather` task queued from the endpoint; runs with no position and no
  profile location are marked `source: none`. "Since day 1" = median of the first 3 runs
  with HR vs the last 3 (with fewer than 7 runs the halves are smaller); needs ≥ 4 runs.
- **AI routing** (`apps/coaching/client.py`): `route_for(operation)` → (provider, model):
  an `AIConfig` row for the operation's tier, else env (`AI_PROVIDER`, `AI_<TIER>_MODEL`).
  Gemini = the `openai` SDK with `base_url=https://generativelanguage.googleapis.com/v1beta/openai/`
  and `GEMINI_API_KEY`. Structured output: strict `json_schema` first; if the provider
  rejects the schema (4xx mentioning schema/response_format) one retry in `json_object`
  mode with the schema in the system prompt, then the same Pydantic validation. Tool
  calling: OpenAI keeps `reasoning_effort="none"`; Gemini gets no reasoning parameter;
  missing tool-call ids are synthesised and Gemini 3 thought signatures
  (`extra_content`) are echoed back. Streaming is not used anywhere in the app. Every call
  logs provider, model, tier, tokens, cost (price table `ModelPrice`, else the built-in
  fallback), latency and status. The per-athlete monthly budget (default
  `AI_MONTHLY_CALL_BUDGET`, or the admin's per-user `ai_budget`) applies to every provider.
  The price table is seeded from the built-in list the first time the admin page reads it.
- **Admin**: `IsAdminUser` (`is_staff`) on every `/api/admin/…` view. Disabling a user sets
  `is_active=false` and blacklists their refresh tokens (access tokens expire within 15
  min). "Last active" = newest of last login and the newest refresh-token issue. Invites
  gained `revoked_at` (revoked codes can't be used). System view: Celery queue lengths =
  Redis `LLEN` of `celery`, `garmin`, `metrics`, `ai`, `planning`; Garmin breaker from the
  shared cache key; Kubernetes via the pod's ServiceAccount (token + CA under
  `/var/run/secrets/kubernetes.io/serviceaccount`, httpx, 4 s timeout) — `GET /api/v1/nodes`,
  `/apis/metrics.k8s.io/v1beta1/nodes`, `/api/v1/namespaces/<ns>/pods`, `…/pods/<own pod>`
  (image tag = git sha), `/apis/batch/v1/namespaces/<ns>/cronjobs/postgres-backup`,
  `/apis/batch/v1/namespaces/<ns>/jobs`. Not in a cluster → `reason: "not_in_cluster"`;
  401/403 → `"forbidden"`. Disk = node ephemeral-storage capacity/allocatable (real disk
  usage would need `nodes/proxy`, deliberately not granted). R2: the backend can't see the
  bucket (`r2.configured: null`) unless `R2_BUCKET` is in its env. `GIT_SHA`/`APP_VERSION`
  env wins over the image tag.
- **Account deletion**: all R14 tables cascade (see apps/athletes/deletion.py).
- **Deploy**: migrations `athletes.0011_r14`, `coaching.0009_r14` (backfills `tier` on old
  log rows), `health.0003_r14`, `planning.0006_r14`. New tasks `planning.weather_checks`,
  `planning.weather_check` (planning queue), `health.heart_weather` (metrics queue); new beat
  entry `weather-checks` — restart worker and beat. New env (all optional):
  `GEMINI_API_KEY`, `GCP_TRIAL_END` (default 2027-01-03), `GCP_CREDIT_INR`, `GIT_SHA`. No
  new Python dependencies. Make an admin with `python manage.py shell -c "from
  django.contrib.auth.models import User; User.objects.filter(username='rohit').update(is_staff=True)"`.

## R15 — contract for Gemini robustness, provider compare, run summary on the watch, share data

All additive except the reminder merge (§C: `run_reviewed` → `run_summary`).

### §A Gemini robustness (admin; staff only, as R14 §14)

**Live model lists.** `GET /admin/ai/providers/` (optional `?refresh=1` bypasses the 1-h cache)
— each provider gains:
```
models: [str],                       # live models.list(), filtered to text chat models;
                                     # the price table rows when the live list can't be read
models_source: "live"|"price_table",
models_fetched_at: datetime|null,
model_info: [ModelInfo]              # one per entry of `models`, same order
ModelInfo = { id: str, priced: bool,                    # has a ModelPrice row
              status: "ok"|"busy"|"no_quota"|"unavailable"|"error"|"unknown",
              checked_at: datetime|null,                # last "Check models" probe
              note: str|null }                          # human sentence for non-ok
```
Filtered out: ids containing tts, image, embedding/embed, audio, live, robotics, computer-use,
transcribe, nano-banana, omni, customtools, realtime, whisper, dall-e, moderation, imagen,
veo, aqa. Gemini keeps `gemini*`/`gemma*` ids (the `models/` prefix is stripped); OpenAI
keeps `gpt-*`, `o1*`, `o3*`, `o4*`, `chatgpt*`.

**Check models.** `POST /admin/ai/models/check/ {provider, models?: [str] (≤ 12), force?: bool}`
→ 202 `{provider, queued: [str], skipped: [str]}`. Runs in the background (Celery `ai` queue):
each queued model gets one tiny prompt ("Reply with OK.", max 5 output tokens), 1.5 s apart,
at most 12 per run, one attempt each (no retry, no fallback). Without `models` the candidates
are the provider's filtered list, never-checked first then oldest-checked. A model checked
in the last 24 h is skipped (listed in `skipped`) unless `force: true`. Results appear in
`model_info` (poll `GET /admin/ai/providers/`). Probes are logged as operation
`admin_check` (no athlete, no budget). 400 for an unknown/unconfigured provider.

Status meaning: `ok` answered; `busy` 503/overloaded (or a per-minute rate 429);
`no_quota` 429 quota/billing (free tier: Pro models need billing); `unavailable` 404 / not
offered to this key; `error` anything else (auth, bad request, timeout).

**Model cards** (what each model is, how fast, how costly). `GET /admin/ai/models/?provider=gemini|openai`
(optional `refresh=1`) → `{provider, source: "live"|"price_table", fetched_at: datetime|null,
models: [ModelCard]}` — one card per entry of the provider's `models` list, same order:
```
ModelCard = ModelInfo + {
  label: str,                                   # "Gemini 3.5 Flash-Lite"
  family: str,                                  # flash-lite | flash | pro | nano | mini | full | other
  known: bool,                                  # false = generic summary derived from the name
  summary: str,                                 # 1–2 plain sentences: what it is good at
  best_for: ["lite"|"fast"|"coach"|"deep"],     # tiers it suits
  speed: "fast"|"medium"|"slow",
  quality: "basic"|"good"|"strong"|"best",
  cost_level: "free_tier"|"$"|"$$"|"$$$",       # free_tier = Gemini, works on the free key
  price_in_per_1m: number|null, price_out_per_1m: number|null,   # USD, from the price table
  est_cost_per_call_usd: {lite: number|null, fast: …, coach: …, deep: …},
                                                # median tokens per call of each tier over the
                                                # last 30 days (defaults when no data) × price
  context_window: int|null,                     # tokens, when known
  free_tier_ok: bool|null,                      # Gemini only: last probe ok (true), no_quota/
                                                # unavailable (false), never probed (null)
  calls: int, avg_latency_ms: int|null,         # our own AIRequestLog, last 30 days
  error_rate: number (0–1), avg_cost_usd: number|null }
```
The static descriptions live in `backend/apps/coaching/model_catalog.py`; unknown ids get a
generic card from the name family (flash-lite = cheapest/fastest, flash = balanced, pro =
strongest/most expensive; OpenAI nano < mini < full).

**One-click provider switch.** `POST /admin/ai/config/switch/ {provider}` → the `config` body
plus `changed: [{tier, model}]`, `unchanged: [{tier, reason}]`. Each tier is pointed at that
provider's recommended model for the tier (the catalog's preference list, skipping models
whose last probe was not ok and, when the live list is known, models not in it; for the env
provider, its env model for the tier is preferred). Stored fallbacks are kept. 400 for an
unknown/unconfigured provider. Per-tier `PUT /admin/ai/config/` is unchanged.

**Per-tier fallback.** `GET|PUT /admin/ai/config/` — each `Tier` gains:
```
fallback_provider: str|null, fallback_model: str|null,   # the stored choice (null = env default)
fallback: {provider, model, source: "db"|"env"} | null,  # the effective fallback; null when it
                                                         # would equal the primary route or its
                                                         # provider has no key
model_status: "ok"|"busy"|"no_quota"|"unavailable"|"error"|"unknown",   # of the primary model
warning: str|null                                        # set when model_status is not ok/unknown
```
PUT items may carry `fallback_provider` + `fallback_model` (both, or both null to go back to
the env default). The primary and fallback model must be in the price table **or** in the
provider's live list (else 400). PUT still succeeds for a non-ok model — show `warning`.

**Call policy** (every app feature; not the admin test/compare/check, which are one shot):
1. Primary route = the tier's `AIConfig` (else env).
2. A 503/500/502/504, an overloaded message, a per-minute 429 or a timeout is retried at most
   2 times with exponential backoff + jitter (≈1.5–3 s, then 3–4.5 s; total sleep ≤ 12 s).
   A quota 429, 404, 401/403 or 400 is not retried.
3. If the primary still fails (any error, including validation failures after its retries),
   the call is made once more on the tier's fallback route (default: the env route for that
   tier, i.e. `AI_PROVIDER` + `AI_<TIER>_MODEL`), with the same retry rule. No fallback
   when it equals the primary.
4. Logging: the failed primary attempt is an `AIRequestLog` row with **`status: "fallback"`**
   (its `error`, `error_kind`, latency); the fallback attempt is its own row (`ok` or `error`).
   Only `ok`/`invalid` rows count towards the monthly budget, so a fallback costs the athlete
   one call.

**Error kinds.** `AIRequestLog.error_kind`: `busy|no_quota|unavailable|auth|bad_request|timeout|other`
(blank for ok rows). `GET /admin/ai/stats/` changes:
- `totals.fallbacks: int` (rows with status fallback in range).
- `by_error_kind: [{error_kind, count}]` (error + fallback + invalid rows in range).
- `recent_errors[]` items now include rows with `status: "fallback"` and gain
  `error_kind: str|null` and `hint: str` — a plain sentence, e.g.
  "Pro models need billing on your Google AI Studio key." (no_quota + gemini + a pro model),
  "Google says this model is busy right now (503); calls were retried and then fell back.",
  "This model isn't available to your key (retired or not offered to new users) — pick another."

### §B Compare providers (admin)
```
CompareResult = { index: int, provider, model, ok: bool, status: "ok"|"error",
                  error_kind: str|null, error: str|null, hint: str|null,
                  text: str (≤ 8000), latency_ms: int, input_tokens: int, output_tokens: int,
                  cost_usd: number, rating: int|null (1–5) }
CompareRun = { id, created_at, created_by: {id, username},
               prompt: str,                      # what was sent (the rendered operation prompt
                                                 # when `operation` was used)
               operation: "insights_summary"|"run_review"|null,
               context_note: str|null,           # e.g. "Insights (last 4 weeks), aggregates only"
               results: [CompareResult] }
```
- `POST /admin/ai/compare/ {prompt?: str (1–4000), targets: [{provider, model}] (2–4, distinct,
  provider configured), operation?: "insights_summary"|"run_review", athlete_id?: int}` →
  201 `CompareRun`. `prompt` is required without `operation`; with an operation it is
  optional and, when given, appended as an extra instruction. `athlete_id` = whose data the
  operation replays (default: your own athlete row); 404 if it doesn't exist; 400 if there is
  nothing to replay (no review for `run_review`). Context = the same aggregate payload the
  feature sends (insights: 4-week aggregates; run_review: the newest run review's comparison
  rows and bullets) — no name, no notes, never the private habit.
  Targets run one after another, one attempt each (no retry, no fallback), each logged as an
  `AIRequestLog` row with operation **`admin_compare`** (no athlete, no budget).
- `GET /admin/ai/compare/?limit=` (1–50, default 20) → `[CompareRun]` newest first.
- `GET /admin/ai/compare/{id}/` → `CompareRun`.
- `PATCH /admin/ai/compare/{id}/ {ratings: [{index, rating: 1–5|null}]}` → `CompareRun`.

### §C Run summary on the watch (web push)
- Reminders: the R13 `run_reviewed` reminder is **replaced** by
  `{key: "run_summary", label: "Run summary", description: "After each run: distance, time,
  pace and heart rate. Shows on your Garmin watch when Garmin Connect mirrors this app's
  notifications.", enabled, time: null}`. **Default ON.** `PATCH /reminders/ {run_summary:
  {enabled}}`; `run_reviewed` is still accepted in PATCH as an alias (deprecated); `time`
  → 400 as before.
- Sent once per run when its post-run review is built (runs that started in the last 24 h
  only). During the athlete's quiet hours it is held and sent at quiet-hours end (5-min beat).
- Payload (service worker shows `title` + `body`; `body` has at most 2 lines split by "\n",
  each ≤ 60 chars; `title` ≤ 30 chars):
```
{ title: "Run 5.2 km · 43:10",
  body: "Pace 6:58 (3 s faster than usual) · HR 141 on target\nNext: rest day",
  url: "/activities/{id}", tag: "run_summary-{id}", kind: "run_summary" }
```
  Pace = run-block pace (else moving pace); "faster/slower than usual" compares with similar
  past runs (the review's typical pace; omitted when within 3 s or no history). HR = run HR,
  "on target"/"above target" against the planned workout's zone top (omitted with no plan).
  "Next:" = the next planned workout's title (shortened) or "rest day" when tomorrow has none;
  the line is left out with no active plan.
  Numbers are in this push only (the athlete's own device); no habit data.
- Frontend: the service worker should use `tag` (replaces an older one for the same run) and
  must not set `silent`. Settings copy: "To see it on your watch: Garmin Connect → Devices →
  Notifications → allow your browser / RunCoach."

### §D Share data — `GET /activities/{id}/share-data/` (own activities only; else 404)
```
{ activity_id, sport, title: str,               # "Morning run" | "Lunch run" | "Afternoon run" |
                                                # "Evening run" | "Night run" (local start hour)
  workout_title: str|null,                      # the planned workout this run completed
  date: date, started_at: datetime, start_local: "YYYY-MM-DDTHH:MM",
  distance_m: number, distance_km: number (2 dp),
  moving_s: int, elapsed_s: int,
  avg_pace_s_per_km: int|null,                  # moving time / distance
  run_pace_s_per_km: int|null,                  # run blocks only (segmentation), if known
  avg_hr: int|null, max_hr: int|null, cadence_spm: int|null,
  elevation_gain_m: number|null, calories: int|null,
  splits: [{km: int, pace_s: int, hr: int|null, distance_m: number, partial: bool}],
                                                # whole km; a last partial split ≥ 100 m has
                                                # partial: true and pace normalised to /km
  best_km: {km: int, pace_s: int} | null,       # fastest whole km
  weather: {temp_c, feels_like_c, humidity, dew_point_c} | null,   # at run start, if fetched
  route: { available: bool, reason: str|null, hidden_endpoints: bool, trimmed_m: int,
           bounds: {south, west, north, east}|null,
           points: [[lat, lon]],                # ≤ 800, simplified, endpoint-trimmed
           km_markers: [{km, lat, lon}] } }
```
Endpoint trimming follows the athlete's `map_hide_endpoints` (first/last 200 m never leave
the server), exactly as `/activities/{id}/route/`.

### R15 backend choices
- **SDK retries off**: the `openai` client is built with `max_retries=0`, so the R15 policy is
  the only retry layer (the SDK's own silent retries would blow the 12-s budget).
- **429 split**: "limit: 0", `insufficient_quota`, per-day quotas and generic quota/billing
  messages → `no_quota` (not retried); per-minute / "rate limit" 429s → `busy` (retried).
- **Validation retries** (`AI_MAX_RETRIES`, schema-invalid JSON) still apply per route; a
  route that keeps failing validation falls back like any other failure.
- **Tool-loop fallback** switches route for the rest of that conversation turn and strips
  Gemini thought signatures (`extra_content`) from earlier assistant tool calls first.
- **Admin one-shot calls** (`admin_test`, `admin_compare`, `admin_check`) never retry or
  fall back; all three are tier `admin`, no athlete, no budget.
- **Run summary** dedupe = one `RunReview` per activity + `pushed_at`; the quiet-hours hold is
  `RunReview.summary_due_at`, drained by the existing 5-min `reminders.send_due` beat. Runs that
  started more than 24 h ago (backfills) never push.
- **Deploy**: migrations `activities.0007_r15`, `coaching.0010_r15`, `reminders.0005_r15`
  (drops `run_reviewed`, adds `run_summary` default true). New Celery task
  `coaching.check_models` (ai queue) — restart the workers. No new env or dependencies.

## R16 — contract for editing workouts (app + chat), the honest coach, dated day metrics, auto-sync

Conventions as R10–R15 (paths under `/api/`, signed-in athlete, own rows only — another
athlete's id → 404; dates `YYYY-MM-DD`; datetimes ISO 8601 with offset; errors
`400 {detail}` unless noted). Every change below is **additive**: no existing key is removed
or changes meaning.

### §A Edit a workout

**Workout JSON** (everywhere: `/calendar/`, `/today/`, `/workouts/{id}/`, plans, chat
attachments) gains:
```
edited_by: "user"|null,            # "user" once the athlete (app or chat) edited it
edited_at: datetime|null,
edited_via: "app"|"chat"|null,
notes: str,                        # the athlete's own notes ("" when none), ≤ 1000 chars
can_edit: bool,                    # planned, today or later, not completed (RACE: notes only)
can_undo_edit: bool,               # edited_by == "user" and still editable
planned: null | {title, kind, duration_s, run_s},   # the generated version (before the
                                   # first user edit); null when not edited
```
Steps of an edited workout carry two extra keys (generated steps are unchanged):
`target: "hr"|"pace"|"none"|"auto"` (what the watch shows for that step) and
`note: str|null`. Step `kind` may now also be `"other"`.

**Editor model — `GET /workouts/{id}/edit/`** (the step editor reads this, not the raw steps):
```
{ workout_id, date, title, kind,
  editable: bool, notes_only: bool,          # notes_only: RACE
  reason: str|null,                          # why not editable ("Already done.", "In the past.")
  notes: str,
  total_s: int, run_s: int, walk_s: int,
  steps: [EditItem],                         # consecutive identical blocks folded into repeats
  planned: null | {title, kind, duration_s, run_s},
  edited_by: "user"|null,
  limits: {total_min_s: 300, total_max_s: 14400, step_min_s: 10, step_max_s: 5400,
           repeat_min: 2, repeat_max: 30, max_steps: 100,
           hr_min: int, hr_max: int,          # resting HR (else 40) .. max HR (else 220−age, else 210)
           pace_min_s: 150, pace_max_s: 1200},  # s/km
  hr: {resting: int|null, max: int|null, ceiling: int, easy_low: int, easy_high: int},
  pace: {easy_low: int, easy_high: int} }      # s/km, the athlete's easy band (fast edge first)

EditItem = EditStep | {repeat: int (2–30), steps: [EditStep] (1–10, no nesting)}
EditStep = { kind: "warmup"|"run"|"walk"|"recovery"|"cooldown"|"strides"|"other",
             duration_s: int (10–5400),
             intensity?: "walk"|"easy"|"moderate"|"hard",   # default by kind: run easy, walk/
                                                            # recovery/warmup/cooldown walk,
                                                            # strides hard, other easy
             target?: "hr"|"pace"|"none"|"auto",            # default: hr if hr_low/hr_high given,
                                                            # else pace if pace_*, else auto
             hr_low?: int|null, hr_high?: int|null,         # bpm
             pace_low?: int|null, pace_high?: int|null,     # s/km; low = FAST edge (smaller number)
             note?: str|null (≤ 80) }
```
`target: "auto"` = the app's default watch target (the R7 rule: run steps their band, walk
steps the gentle band). `"none"` = no target on the watch. In GET, a generated step that has
an HR band comes back as `target: "hr"`; generated `stride` → `strides`, `interval` → `run`
with intensity `hard`.

**`PATCH /workouts/{id}/edit/`** — body: any of
```
{ steps?: [EditItem],                       # replaces all steps (applied first)
  total_minutes?: number (5–240),           # scale every step to this total (whole result
                                            #   rounded so the steps sum exactly to it)
  add_minutes?: number (−120…120, ≠ 0),     # ± minutes …
  apply_to?: "run"|"walk"|"both",           # … spread over the run parts (default), walk
                                            #   parts or all parts, proportionally, 30-s grid
  add_walk_breaks?: number (1–30),          # split every run step longer than N+1 min into
                                            #   N min run / 1 min walk; total time unchanged
  hr_low?: int, hr_high?: int,              # set this HR range (target "hr") on every
                                            #   non-walk step (both required together)
  notes?: str (≤ 1000),
  dry_run?: bool }                          # validate + preview + warnings, nothing saved
```
Order when several are sent: steps → total_minutes → add_minutes → add_walk_breaks →
hr range → notes. Run parts = non-walk steps of intensity easy (if none: every non-walk
step except strides); walk parts = walk-intensity steps.
- 200 → `EditResponse`:
```
{ ...Workout,                               # the saved workout (dry_run: the preview, unsaved)
  warnings: [{key: "run_increase"|"hr_above_ceiling"|"hard_days_in_a_row"|"long_run_share",
              text: str}],                  # plain words; NEVER block the save
  edit: {dry_run: bool, changed: bool,
         before: Brief, after: Brief,       # Brief = {title, duration_s, run_s, walk_s}
         summary: str},                     # "Sat 12 Oct: 40 → 45 min"
  watch: {was_on_watch: bool,
          status: "not_on_watch"|"updated"|"unchanged"|"pending"|"failed",
          detail: str} }
```
  `garmin_status` in the body is read after the re-send. dry_run → `watch.status`
  `"not_on_watch"` or `"pending"` (nothing is sent).
- 400 `{detail}` on invalid input (limits above; HR outside hr_min..hr_max or low ≥ high;
  pace outside 150–1200 s/km or low > high; nested repeat; unknown kind; no field given).
- 409 `{detail}` when not editable: completed, skipped, in the past, or RACE with anything
  but `notes`.
- Warnings (computed against the **generated** version, i.e. `planned` when already edited):
  `run_increase` running time > +25 %; `hr_above_ceiling` any HR target top above the
  athlete's `hr_ceiling`; `hard_days_in_a_row` this session is hard (INTERVALS/TEMPO/LONG/
  RACE, ≥ 5 min of moderate/hard steps, or an HR target low above the easy top) and the day
  before or after has a hard session; `long_run_share` this session's running > 40 % of
  its Mon–Sun week's running (week has ≥ 2 runs).
- Saving marks the workout `edited_by: "user"`; the first edit stores the generated version
  (`planned`). Title minutes ("45m easy aerobic run", "Long run 60m") follow the new total;
  duration, load and fueling are recomputed.
- **Watch**: if the workout was on the watch (`garmin_workout_id` set) it is re-sent right
  away through the normal send job (registry sweep, old copy deleted, new one uploaded and
  scheduled). The request waits up to 20 s: `updated`/`unchanged`; still queued → `pending`
  (it completes in the background; `garmin_status` stays `changed` until then); breaker
  open / Garmin refused → `failed` (UI: "Update on watch"). Never fails the save.
- **Garmin payload** for steps with `target`: `"hr"` → custom HR range (as R7, also on walk
  steps); `"pace"` → `targetType {workoutTargetTypeId: 6, workoutTargetTypeKey: "pace.zone",
  displayOrder: 6}`, `targetValueOne` = slow edge, `targetValueTwo` = fast edge, in **m/s**
  (1000 / s-per-km, 4 dp); `"none"` → no.target; `"auto"`/absent → the R7 rule. The
  athlete's notes are appended to the Garmin description. Generated workouts produce exactly
  the same payload (and hash) as before.
- **Protected**: an edited workout is never changed by auto-adjust (R13 §1), the weekly
  adaptation (R6 §2) or weather swaps (R14 §3, neither moved nor swapped with). Re-flow
  (training days changed) may move its date but never drops it; re-layout (runs per week)
  leaves a week that holds an edited session exactly as it is (content and dates; a
  `notes` line says so) and re-splits the other weeks. The
  morning check-in "Use this" is the athlete's own action and still applies.

**`POST /workouts/{id}/edit/undo/`** → 200 `EditResponse` (warnings `[]`) with the generated
version restored, `edited_by: null`, watch re-sent as above. 409 `{detail}` when not edited
or no longer editable.

**`POST /plan/week-edit/`** — body:
```
{ week_start: date,                          # the 7 days week_start … week_start+6 (the plan
                                             #   week header's start; need not be a Monday)
  action: "add_minutes"|"scale"|"add_walk_breaks"|"set_hr_range",
  value: number | {hr_low, hr_high} | [low, high],
        # add_minutes: −60…60 (≠ 0) min per session; scale: factor 0.5–1.5;
        # add_walk_breaks: 1–30 (run minutes between 1-min walks); set_hr_range: the range
  apply_to?: "run"|"walk"|"both",            # add_minutes only (default run)
  kinds?: [str],                             # only these workout kinds (EASY, LONG, …)
  dry_run?: bool }
```
Matches every workout of the active plan in that week that is planned, today or later, not
completed, not RACE/REST, with steps (and of `kinds`). → 200
```
{ week_start, week_end, action, dry_run: bool,
  changed: [{workout_id, date, title, before: Brief, after: Brief, summary: str}],
  skipped: [{workout_id, date, title, reason: str}],     # e.g. would drop below 5 min
  warnings: [{workout_id, date, key, text}],
  watch: {updated: int, unchanged: int, pending: int, failed: int, not_on_watch: int} }
```
400 on bad input; 404 `{detail}` without an active plan. Changed workouts are marked
`edited_by: "user"` exactly like a single edit.

### §B Coach chat edits — and never pretends

New chat tools (same service, same validation, warnings and watch re-send; `edited_via: "chat"`):
```
edit_workout(id, total_minutes?, add_minutes?, apply_to?, steps?, hr_low?, hr_high?,
             add_walk_breaks?, notes?, confirmed?)
edit_week(week_start, action, value, kinds?, apply_to?, confirmed?)
```
Tool results: success `{status: "updated", workout_id, date, before, after, summary,
warnings: [str], watch_status}` (edit_week: `{status: "updated", changed: [...], skipped,
warnings, watch}`); `{status: "needs_confirmation", increase_pct, summary, message}` when the
change adds more than **20 %** running to a session (vs its generated version; total time
for a session without running) and `confirmed` is not true — nothing is saved, the coach must
ask and call again with `confirmed: true`; `{error: str}` otherwise.

**Chat message JSON** (`GET /chat/threads/{id}/messages/`, the POST reply's `assistant`) gains
```
plan_changed: [{workout_id: int, date: date, summary: str}]   # [] when nothing changed
```
filled from mutating tools that succeeded in that turn (edit_workout, edit_week,
move_workout, skip_workout, clear_day). The POST reply also has top-level `plan_changed`
(same list). UI: "Plan updated" chip → the workout; invalidate Plan/Today/calendar queries.

Also (added after the first contract commit):
```
needs_confirmation: null | {workout_id: int, date: date,      # edit_workout, or …
                            week_start: date,                  # … edit_week (one of the two)
                            summary: str,                      # "Thu 8 Oct: 40 → 55 min (+38%)"
                            increase_pct: int}
```
on the message JSON and top-level in the POST reply: set when an edit tool answered
`needs_confirmation` in that turn and no later call in the same turn applied it; else null.
UI: "Yes, do it / No" buttons — they just send a chat message ("Yes, do it." / "No, leave
it."); the coach then calls the tool again with `confirmed: true` (or doesn't).

**Honesty guard** (server side, every chat turn): if the final reply claims a change ("I've
updated/increased/changed/moved/extended/shortened/added/adjusted/rescheduled/skipped…" next
to a plan word — workout, run, session, plan, week, minutes, watch …, or "… has been
updated/moved …") and no mutating tool (the five above, or propose_plan) succeeded in the
turn, the model is re-prompted once with the facts (which tools ran and what they returned)
and told to either make the change with a tool now or say plainly that nothing changed. If
the second reply still claims an unmade change (or the re-prompt fails), the reply gets the
line "_Correction: nothing in your plan was changed in this reply._" appended. Each firing
is logged (`coaching.chat` warning) and stored on the message (`ChatMessage.guard`, not in
the API).

### §C Dated day metrics + freshness

Additive `date`/`as_of` keys; `stale` flags follow one rule (`apps/health/freshness.py`):
`stale` is true when the athlete has wellness data at all, it is 05:00 or later local, and
today's row has no sleep **or** no readiness yet. `stale_reason`:
`"sleep_missing"|"readiness_missing"|"both_missing"|null`; `stale_text` the one-liner
("Showing yesterday's sleep — your watch hasn't synced last night yet.") or null.
`latest_sleep_date` / `latest_readiness_date` = newest day that has it (any age) or null.
```
Freshness = { as_of: datetime, today: date, stale: bool, stale_reason, stale_text,
              latest_sleep_date: date|null, latest_readiness_date: date|null,
              last_sync_at: datetime|null }
```
- `GET /today/` gains top-level `as_of`, `freshness: Freshness`, and every `reasons[]` item
  gains `date: date|null` — the day the value is from (sleep, HRV, readiness: today; resting
  HR, body battery: today or yesterday; rpe, alcohol: yesterday; load, heat, air, pain,
  illness: today).
- `GET /briefing/today/` gains `as_of`, `freshness`, and `readiness.date` (today or null).
- `GET /insights/` gains `as_of`, `freshness`; `readiness.date`, `hrv.last_night_date`,
  `resting_hr.current_date`, `vo2max.date` (when vo2max is present), `body_battery.date`
  and `stress.date` (newest day in the series, or null).
- `GET /health/day/summary/` gains `as_of` (datetime) and `freshness`.
- `GET /health/sleep/` gains `as_of` and `last_night_date` (newest night in `nights`, or null).
- `GET /health/readiness-forecast/` gains `as_of` and `today.date` (the day `today.score`
  is from, or null).
UI rule (spec): show a date only when it isn't today / last night.

### §C Auto-sync

**`GET /sync/status/`** →
```
{ connected: bool,                    # stored Garmin flag (no probe — cheap)
  last_sync_at: datetime|null,        # last successful sync
  last_attempt_at: datetime|null,     # last sync start (manual, auto or scheduled)
  running: bool,                      # a sync for this athlete is in progress
  breaker_open: bool,                 # Garmin rate-limit breaker
  can_sync_now: bool,                 # connected and not running and breaker closed
  auto_sync_due: bool,                # can_sync_now, local time ≥ 05:00, last_sync_at older
                                      #   than 60 min (or never), no attempt in the last 30 min
  next_auto_sync_at: datetime|null,   # earliest time an auto POST will run (null: now/never)
  min_interval_s: 1800 }
```
**`POST /garmin/sync/ {auto: true}`** (the existing endpoint; manual calls unchanged): runs
only when an attempt is allowed; otherwise **200** `{skipped: "recent"|"running"|
"breaker_open"|"not_connected"|"too_early", status: SyncStatus}` without calling Garmin. When it
runs: the usual sync body plus `status: SyncStatus`. Server-side: at most one auto attempt per
30 min per athlete (any sync start counts), and a sync never runs twice at once (a
second POST while one runs → `skipped: "running"`; a manual POST then → 409 `{detail}`). The
frontend should call it when `auto_sync_due` is true (still counts against the `garmin`
10/hour throttle).

### Run map: `GET /activities/{id}/route/?full=1`
`full=1` (or `true`) returns the **untrimmed** route — true start and finish,
`hidden_endpoints: false`, `trimmed_m: 0` — for the owner's own in-app map. Same body
shape as the default call. Endpoint trimming (`map_hide_endpoints`) still applies to the
default call (no `full`) and to every share output (`/share-data/`, exports, the routes
overlay). Owner only: another athlete's id → 404 as before.

### R16 backend choices
- Edited workouts store their generated version in `PlannedWorkout.pre_edit`; undo restores
  it. Steps edited in the editor are stored flat (repeat blocks expanded); GET folds them.
- Chat `+20 %` is measured against the generated version, so repeated small edits can't
  ratchet past it without confirmation.
- Deploy: migrations `planning.0008_r16` (PlannedWorkout `edited_by, edited_at, edited_via,
  notes, pre_edit`), `coaching.0011_r16` (ChatMessage `plan_changed, guard, needs_confirmation`). No new env,
  tasks or dependencies.

## R17 — contract for recovery routine, bad-data filter + data review, illness mode, coach memory page, deleting activities

Conventions as R10–R16 (paths under `/api/`, signed-in athlete, own rows only — another
athlete's id → 404; dates `YYYY-MM-DD`; datetimes ISO 8601 with offset; errors
`400 {detail}` unless noted). Every change is **additive**: no existing key is removed or
changes meaning. **Rohit's rule for R17: nothing is ever excluded or removed
automatically.** The app *suggests*; only the athlete's explicit decision excludes a run
or a day from trends, or removes an activity. Raw data is never modified.

### §1 Recovery routine after runs

`GET /activities/{id}/recovery/` →
```
Recovery = { activity_id: int, available: bool,
             reason_unavailable: null|"not_a_run",    # walks, rides, strength → steps []
             minutes: int,                    # 5–8 (sum of non-optional steps, rounded)
             total_s: int,                    # non-optional steps, both sides counted
             reason: str,                     # why this set: "Hilly 52-min easy run — extra calf and quad time."
             focus: [str],                    # tags: "long"|"hard"|"hills"|"cadence"|"ground_contact"|"pain"|"injury_watch"
             steps: [Step],
             avoided: [{area: str, text: str}],   # painful areas softened/skipped ("Knee (left): skipped the quad stretch — never stretch into pain.")
             notes: [str],                    # always includes "Ease into each stretch — mild tension, never pain."
             done: bool, done_at: datetime|null,
             streak: {current: int, best: int},   # runs in a row with the routine done
             show_until: datetime }           # run end + 6 h (Today card visibility)
Step = { key: str,            # "cooldown_walk"|"calf_stretch"|"hamstring_stretch"|"quad_stretch"|
                              # "hip_flexor_stretch"|"glute_stretch"|"it_band_stretch"|
                              # "adductor_stretch"|"lower_back_stretch"|"calf_roll"|
                              # "hamstring_roll"|"quad_roll"|"it_band_roll"|"glute_roll"
         title: str, seconds: int,           # per side when per_side
         per_side: bool, cue: str,
         figure: str,                        # walk|calf|hamstring|quad|hip_flexor|glute|it_band|
                                             # adductor|lower_back|calf_roll|hamstring_roll|
                                             # quad_roll|it_band_roll|glute_roll
         optional: bool,                     # foam-roll variants (not in `minutes`)
         softened: bool,                     # shortened/gentler because of a pain report
         area: str|null }                    # body area worked (calf, hamstring, quad, hip, glute, lower_back, adductor)
```
- Pure `analysis/recovery_routine.py`. Base: 2–3 min cool-down walk (`cooldown_walk`, first)
  + calf, hamstring, hip flexor (+ quad, glute on longer/harder runs). Hills (≥ 15 m
  gain per km) → longer calf and quad; long (≥ 60 min) → + glute/piriformis and lower
  back; hard (INTERVALS/TEMPO/RACE or ≥ 20 % in Z4–Z5) → + adductor and IT band; low
  cadence (< 160) or high ground contact (> 280 ms) → longer calf hold. Pain reports for
  that run or the last 3 days (R13 §3) at severity 1 → stretch for that area softened (half
  time, gentler cue); severity ≥ 2 → skipped and listed in `avoided`. Injury-watch flags
  (risk moderate/high) → softened only. Trimmed/extended to stay within 5–8 min
  (non-optional). Foam-roll steps are `optional: true` and come last.
- `POST /activities/{id}/recovery/done/ {skipped?: [step key]}` → 200
  `{activity_id, done: true, done_at, streak: {current, best}, new_badges: [{key, label}]}`.
  Idempotent (second call → same `done_at`). 409 `{detail}` for a non-run.
- `GET /recovery/today/` → `{routine: null | {activity_id, minutes, title: "Recovery · 6 min",
  show_until, done}}` — the newest run whose `show_until` is still ahead and which is not
  done (the Today card).
- Achievements gain group `recovery` (unit "runs"): `recovery_streak_3|7|14` = the
  routine done after N runs in a row. Shown once the athlete has done one routine. The
  streak counts runs from the first routine done; a run without it breaks the streak.
- Reminders gain the event key `recovery_ready` ("Recovery routine ready", **off by
  default**, `time: null`; PATCH with `time` → 400). Sent once per run when a run from the
  last 6 h is processed and not during quiet hours: `{title: "Recovery routine ready",
  body: "6 min for your legs after that run.", url: "/activities/{id}?recovery=1",
  tag: "recovery"}`.

### §2 Bad-data filter (HR spikes, GPS jumps) — suggestions only

Pure `analysis/data_quality.py`, run during derivation for every activity with records;
the result is stored in `ActivityQuality` (one row per activity). The cleaned series is
recomputed from the raw records + the stored parameters whenever needed; **records are
never changed.**

```
Quality = { version: int, score: int,             # 0–100 (100 = nothing found)
            status: "clean"|"fixed"|"review",     # review = something for the athlete to decide
            chip: str,           # "Clean" | "Fixed 2 HR spikes" | "Check this run — wrist HR unreliable"
            summary: str,        # one plain sentence of what was found / done
            flags: [Flag], counts: {<kind>: int},
            hr_fixed_s: int, gps_fixed_s: int,    # seconds affected
            hr_fixed_pct: int, gps_fixed_pct: int,
            affected: [str],     # "avg_hr"|"hr_drift"|"time_in_zone"|"heart_adaptation"|"pace"|"distance"|"splits"|"route"|"records"
            suggestion: "exclude"|null,           # score < 50 → suggest leaving it out of trends
            suggestion_reason: str|null,          # "Wrist HR unreliable" | "GPS unreliable"
            decision: null|"include"|"exclude",   # the athlete's choice; null = undecided
            excluded_from_trends: bool,           # true ONLY when decision == "exclude"
            use: "cleaned"|"raw",                 # what analysis uses for this run now
            use_default: "cleaned"|"raw",
            use_choice: null|"cleaned"|"raw",     # the athlete's explicit choice
            use_suggestion: "cleaned"|null,       # default is raw but fixes exist → suggest cleaned
            pending_review: bool,                 # (suggestion and no decision) or (use_suggestion and no use_choice)
            info: str }                           # the (i) text
Flag = { kind: "hr_cadence_lock"|"hr_spike"|"hr_flatline"|"hr_above_max"|
               "gps_speed"|"gps_teleport"|"gps_drift"|"pause_mismarked",
         start_s: number, end_s: number, severity: "low"|"medium"|"high",
         fix: "interpolated"|"masked"|"flagged",  # flagged = noted, nothing changed
         text: str }
```
**Rules** (definitions also in the module docstring; all time-based, smart recording safe):
- `hr_cadence_lock`: |HR − cadence| ≤ 5 continuously for > 60 s (cadence ≥ 120 spm) →
  HR masked over the span.
- `hr_spike`: HR jumps > 25 bpm within < 5 s with no matching pace change (speed change
  < 15 %) and returns within 10 bpm of the pre-jump level within 60 s → HR linearly
  interpolated across it. A jump that doesn't come back is left alone (real).
- `hr_flatline`: the same HR value for ≥ 120 s while moving → masked (60 s flagged real
  steady-state plateaus in testing).
- `hr_above_max`: HR above the athlete's max HR + 3 (220 when unknown) → masked.
- `gps_teleport`: > 50 m between samples ≤ 1.5 s apart → position masked, distance
  increment replaced by the plausible one (speed sensor / neighbours).
- `gps_speed`: implied speed > 7 m/s (foot sports only) → as above.
- `gps_drift`: stopped (cadence < 30) for ≥ 30 s while distance grows ≥ 25 m → distance
  held flat, speed 0.
- `pause_mismarked`: ≥ 60 s stationary while the timer ran, or a ≥ 10 s recording gap
  across which you moved ≥ 20 m → flagged only.
- Score = 100 − min(60, 150 × HR-fixed share) − min(40, 120 × GPS-fixed share)
  − 2 per spike (max 10) − 2 per pause flag (max 6).
- **`use` default**: `cleaned` when nothing was found or the only fixes are `hr_spike`
  interpolations; otherwise `raw` with `use_suggestion: "cleaned"`. The athlete's
  `use_choice` always wins. With `use: "raw"` analysis sees the raw stream exactly as
  before R17.
- **Trends honour only an explicit `decision: "exclude"`.** An excluded run is left out
  of: progress (`/progress/`), compare run metrics, form, heart adaptation, computed
  records (`/health/records/` computed keys), run-review "typical" baselines. It is
  **never** removed from training load, weekly volume, plan compliance, achievements or
  the activity list (leaving load out would make the plan harder).
- "Downstream analysis uses the cleaned series" = segmentation, metrics (HR drift, zones,
  averages), heart adaptation, progress (fastest 1 km), share splits, chat splits, the
  route, compliance HR, all read the series chosen by `use`.

Endpoints:
- `quality: Quality|null` is added to `GET /activities/{id}/`, `GET /activities/{id}/route/`
  and `GET /activities/{id}/share-data/` (null = not processed yet).
- `GET /activities/{id}/quality/` → `{activity_id, quality: Quality|null,
  series: [{t: int, hr_raw: number|null, hr_clean: number|null, fixed: bool}]}` (≤ 320
  bucket-averaged points; `fixed` = the bucket contains a masked/interpolated HR sample →
  grey it).
- `PATCH /activities/{id}/quality/ {decision?: "include"|"exclude"|null, use?: "cleaned"|"raw"|null}`
  → `{activity_id, quality}`. `null` resets to undecided/default. Changing `use`
  re-derives that run immediately (segments/metrics follow). 400 on bad values.
- `GET /activities/{id}/series/` points gain `hr_clean: number|null` and `hr_fixed: bool`
  (`hr` stays the raw value).

### Data review — `GET /data-review/`, `POST /data-review/decide/`

One list of "Review these days/runs?" items, all reversible.
```
GET /data-review/?all=0|1      # default: pending only; all=1 adds decided items (last 180 days)
→ { pending: int, items: [Item] }
Item =
 | { kind: "run", id: int (activity id), date, title: str, score: int,
     suggestion: "exclude"|null, suggestion_reason: str|null, use_suggestion: "cleaned"|null,
     decision: null|"include"|"exclude", use_choice: null|"cleaned"|"raw",
     pending: bool, text: str }          # "Wrist HR looks unreliable on Tue's run — leave it out of trends?"
 | { kind: "illness", id: int (illness id), type, label, start: date, end: date,  # end = recovered_on or today
     days: [{date, decision: null|"include"|"exclude", has_data: bool}],
     decision: null|"include"|"exclude"|"mixed",
     pending: bool, text: str }          # "You were sick 3–6 Oct — resting HR and HRV may look off. Leave those days out of trends?"
 | { kind: "deleted_in_garmin", id: int (activity id), date, title: str,
     detected_at: datetime, decision: null|"remove"|"keep", pending: bool,
     text: str }                         # "This run is no longer in Garmin Connect — remove it here too?"
```
Ordered newest first. `pending` counts items with `pending: true`.

`POST /data-review/decide/ {items: [Decision]}` (1–200 items, all-or-nothing) →
`{updated: int, items: [Item]}` (the affected items, re-read).
```
Decision = {kind: "run", id, decision?: "include"|"exclude"|null, use?: "cleaned"|"raw"|null}
         | {kind: "day", date, decision: "include"|"exclude"|null}
         | {kind: "illness", id, decision: "include"|"exclude"|null}     # every day of it
         | {kind: "deleted_in_garmin", id, decision: "remove"|"keep"}
```
`null` = back to undecided (reversal). `remove` performs the same delete + tombstone as
`DELETE /activities/{id}/` (undo: `POST /activities/deleted/{id}/reimport/` — re-fetches
it only if Garmin still has it); `keep` stops the question for that activity.
400 `{detail}` on an unknown kind/id/date or bad value (nothing is saved).

**Illness days are flagged, never auto-excluded.** Every day from an illness's start to
its recovery (or today) is `flagged` with reason `"illness"`. They stay in every trend
unless the athlete excludes them. Day decisions `exclude` are honoured by: the morning
check-in baselines (28-day HRV / resting-HR means), compare (`/health/compare/`
wellness metrics), day trends (`/health/day/trends/`), weekly and monthly report wellness
averages, and the R9 habit impact reports. Annotations:
- `/health/day/?date=` gains `flagged: null | {reason: "illness", text, illness_id,
  decision: null|"include"|"exclude"}`.
- `/health/day/trends/` gains top-level `flagged_days: [{date, reason: "illness",
  excluded: bool}]`; excluded days' values are left out of the series and averages.

### §10 Illness mode
```
Illness = { id, type: "cold"|"flu"|"stomach"|"injury"|"other",
            type_label: str,                    # "Cold" | "Fever / flu" | "Stomach bug" | "Injury" | "Other"
            symptoms: "above_neck"|"below_neck",
            fever: bool,                        # default true for flu
            start_date: date, expected_days: int|null, note: str,
            status: "active"|"recovered",
            recovered_on: date|null, days_off: int|null,  # recovered_on − start_date
            days_so_far: int,                   # active: today − start_date + 1
            paused_workouts: int,               # how many sessions it paused
            advice: [str],                      # plain words, non-medical
            see_doctor: [str],                  # "See a doctor if …" lines
            return_block: null | ReturnBlock,
            race_warning: null | {race_id, name, date, days_after_block: int, text},
            created_at, updated_at }
ReturnBlock = { rule: "short"|"week"|"rebuild",
                label: str,                     # "2 easy sessions" | "One easy week" | "2-week rebuild"
                start: date, end: date,         # first/last day of the block
                resumes_on: date,               # the plan continues from here
                sessions: [{workout_id: int|null, date, title, kind: "EASY"|"RUN_WALK",
                            duration_s: int, hr_cap: int|null, pct_of_usual: int,
                            status: str|null}],     # workout status, null without a plan
                usual_duration_s: int,          # the "previous duration" reference
                note: str }
```
- `GET /illness/` → `{active: Illness|null, history: [Illness]}` (history = recovered,
  newest first, ≤ 20). `GET /illness/history/` → `[Illness]` (all, newest first).
- `POST /illness/ {type, symptoms? (default above_neck; flu → below_neck allowed),
  fever? (default type == "flu"), start_date? (default today; today−14 … today),
  expected_days? (1–60), note? (≤ 200)}` → 201 Illness. 409 `{detail}` when one is already
  active.
- `PATCH /illness/{id}/` (active only; else 409) any of `type, symptoms, fever,
  expected_days, note` → Illness.
- `POST /illness/{id}/recover/ {date? (default today; start_date … today), dry_run?}` →
  200 Illness (`status: "recovered"`, `return_block` set). `dry_run` previews, nothing
  saved. 409 when not active.
- `DELETE /illness/{id}/` (active only — "started by mistake") → 204; un-pauses
  everything it paused (future dates), no return block. 409 otherwise.
- **While active**: every `planned` workout of the active plan dated today or later
  (from max(start_date, today)) gets `status: "paused"` — user-edited ones too, with
  their content untouched. RACE workouts are never paused. Planned strength sessions are
  paused too. Paused copies on the watch are removed through the Garmin registry (the
  normal delete job). Paused workouts are left out of `/today/`, auto-adjust, weather
  swaps, re-flow, re-layout, the weekly adaptation, fueling and the ICS feed. The
  strength top-up and weekly adaptation skip the athlete.
- Workout JSON gains `paused_by_illness: int|null` and `illness_return: int|null`
  (the illness id when it is a return-block session); `status` may be `"paused"`.
  Strength JSON `status` may be `"paused"`.
- `/today/` gains top-level `illness: null | {id, type, type_label, start_date,
  days_so_far, advice: [str]}`; while active `verdict: "rest"`, headline "Rest and get
  well", `note` = the first advice line, `workout: null`, `adjusted: null`, and the
  `illness` reason is in `reasons`. `/briefing/today/` gains `illness` (same object);
  `focus = {key: "illness", text}`.
- Reminders while active: `morning_checkin` says "Rest day — focus on getting well."
  (no run talk); `best_run_time` is not sent.
- Weekly report gains `illness: [{id, type, type_label, start, end, days_in_week}]` and a
  went-well line "You rested while unwell — the right call."; monthly report gains
  `illness: [{id, type, type_label, start, end, days_in_month}]`.
- Streaks don't break: illness days are neutral for `run_streak` (they neither count nor
  break it) and a Mon–Sun week containing an illness day with < 2 runs is skipped over by
  `consistent_weeks` (neither counts nor breaks).
- Chat tools: `set_illness(type, symptoms?, fever?, start_date?, expected_days?, note?)` →
  `{status: "started", illness: {...}, paused: int}` | `{error}`;
  `recover_illness(date?)` → `{status: "recovered", return_block, race_warning}` | `{error}`.
  Both count as plan changes (`plan_changed` chips). The model sees only type, dates and
  counts.
- **Return rules** (`planning/illness.py`, pure). days_off = recovered_on − start_date.
  Reference "usual" duration = median moving time of runs in the 28 days before
  start_date (≥ 2 runs), else median of the paused run workouts, else 30 min.
  - `short` (days_off ≤ 3, no fever, above the neck): 2 sessions (days_off ≤ 1) or 3, at
    50 / 60 / 70 % of usual; EASY.
  - `week` (4–7 days, no fever, above the neck): one easy week (7 days), sessions at
    50 / 60 / 70 / 80 % (then 80 %); EASY.
  - `rebuild` (> 7 days, or fever, or below the neck): 7 days (14 when days_off > 14, or
    fever with days_off > 7). First week RUN_WALK (2 min run / 1 min walk) at 40 / 50 /
    60 %; second week EASY at 60 / 70 / 80 %.
  - Injury: same day rules, the first 2 sessions are RUN_WALK, "stop if it hurts".
  - Block starts the day after recovery; with fever or below-the-neck symptoms 2 days
    after ("symptom-free for 24–48 h first").
  - Sessions sit **only on dates where the paused plan had a run** (never on a plan rest
    day). Duration = min(pct × usual, that day's planned duration), ≥ 10 min, whole
    minutes. HR cap = easy top − 10 bpm for the first 2 sessions, − 5 after (never above
    the plan's own cap). They are new PlannedWorkouts in the active plan
    (`illness_return` set); the paused originals on those dates stay `paused` (content
    kept). Without an active plan the block is advice only (`workout_id: null`, dates on
    the athlete's available days).
  - Paused workouts dated on/after `resumes_on` go back to `planned` (edited ones exactly
    as edited); earlier paused ones stay `paused` as history. Nothing is re-sent to the
    watch automatically (use "Send week to watch").
  - `race_warning` when a race of the plan falls inside the block or ≤ 14 days after
    `resumes_on`. The race itself is never moved.
- Health data during illness: see "Illness days are flagged" above.

### §16 Coach memory page
```
Fact = { id, text: str (≤ 300), category: "health"|"schedule"|"goals"|"other",
         category_label: str,          # "Injuries & health" | "Schedule & preferences" | "Goals" | "Other"
         source: "chat"|"checkin"|"app",   # stored "manual" → "app"
         pinned: bool, created_at, updated_at, edited: bool }
```
- `GET /memory/` → `[Fact]` (as before, with the new keys; pinned first, then newest).
  `GET /memory/?grouped=1` → `{count, pinned: int, groups: [{key, label, facts: [Fact]}]}`
  (all four groups, fixed order, possibly empty).
- `POST /memory/ {text, category?, pinned?}` → 201 Fact (200 + existing when the text is
  already known). `category` defaults to a keyword guess.
- `PATCH /memory/{id}/ {text?, category?, pinned?}` → Fact. Same text as another fact →
  400 `{detail: "The coach already knows this."}`.
- `DELETE /memory/{id}/` → 204.
- Pinned facts (max 10; an 11th → 400) are always in the chat context; then the newest
  others up to 40 in total. Edits are what the next chat turn uses.
- **Private habit never stored**: any fact (app, chat tool, automatic extraction,
  check-in) that mentions the private habit is refused — POST/PATCH → 400
  `{detail: "The private habit is never stored in the coach's memory."}`; chat/extraction
  silently drop it.
- Check-in notes: durable facts the check-in note extraction finds are added with
  `source: "checkin"` (same filter).

### Deleting activities
- `DELETE /activities/{id}/` → 200 `{deleted: id, tombstone_id: int, workouts_reopened: [id],
  records_removed: [key]}`. Removes the activity and everything derived from it
  (records, segments, metrics, quality, review, recovery log, heart stats, weather,
  shoe assignment, its check-in journal entry, the raw FIT file, cached routes/splits).
  A planned workout it completed goes back to `planned` (the UI shows past planned ones
  as missed); a strength session it auto-completed goes back to planned. Computed PR
  events dated that day are removed and re-evaluated (badges already earned stay, as in
  R10). A tombstone (Garmin id and/or file hash) stops every later sync, backfill,
  reingest or re-upload of the same file from bringing it back.
- `GET /activities/deleted/` → `[{id (tombstone id), garmin_activity_id: int|null,
  date, sport, distance_m, deleted_at, reason: "user"|"deleted_in_garmin",
  can_reimport: bool}]` newest first.
- `POST /activities/deleted/{id}/reimport/` → 200 `{reimported: bool, activity_id: int|null,
  detail}`: removes the tombstone, then re-downloads from Garmin (garmin queue, waits
  ≤ 20 s) when it has a Garmin id. Garmin no longer has it → `reimported: false`
  (tombstone gone anyway). 503 `{detail}` when Garmin can't be called (breaker /
  not connected; tombstone kept). A FIT upload (no Garmin id): tombstone removed,
  `reimported: false`, "Upload the file again."
- **Deleted in Garmin**: activities RunCoach has that Garmin no longer lists are found
  (never deleted automatically) by (a) the daily slow sync — one `get_activities(0, 100)`
  call; the fully fetched window is from the day after the oldest listed entry (all 60
  days when fewer than 100 came back) and only RunCoach activities of the last 60 days
  inside that window, older than 2 h, are compared; and (b) a full backfill listing. Each
  becomes a `deleted_in_garmin` data-review item (above). "keep" is remembered; "remove"
  = the delete above with reason `deleted_in_garmin`.

### Experiments — up to 3 at once (R17 change to R14 §7)
- `POST /experiments/`: at most **3** scheduled/active experiments → a 4th is 409
  `{detail: "You already have 3 experiments running — stop one first."}`. The same
  template (for `custom`: the same habit) overlapping in dates with an open one → 400.
- Every `Experiment` (list, detail, create, stop, active) gains
  `overlapping: [{id, title, start, end, days}]` (other experiments whose window overlaps
  this one; `days` = number of overlapping days). The detail `result` gains the same
  `overlapping` plus `overlap_note: str|null` — "Another experiment ran at the same time,
  so the changes can't be pinned on one of them." when the list is non-empty.
- `GET /experiments/active/` → `{experiment: Experiment|null` (unchanged: the oldest active
  one, else a recently completed undecided one)`, active_list: [Experiment], max_active: 3}`.
  `active_list` = every active experiment (oldest start first) then completed ones still
  waiting for keep/stop (≤ 7 days).

### R17 backend choices
- Only an explicit `decision: "exclude"` removes a run from trend analyses; only a day
  decision `exclude` removes a day's wellness numbers. Load, volume, compliance,
  achievements and the activity list never drop anything.
- The cadence-lock rule is the spec's (|HR − cadence| ≤ 5 for > 60 s). A runner whose real
  HR sits at their cadence would be flagged too — which is why the default `use` stays
  `raw` for every fix except spike interpolation, and the athlete decides.
- Illness → ids on PlannedWorkout/StrengthSession are plain integers
  (`paused_by_illness`, `illness_return`), not FKs, to keep planning/health migrations
  independent. Starting a new plan while unwell does not pause it (out of scope).
- A deleted activity's computed PR events dated that day are removed; badges already
  earned are kept (R10 rule). A data-review "remove" is the same delete.

### R17 deploy
- Migrations (new models cascade from the Athlete; account deletion covers them):
  `activities.0008_r17` (`ActivityQuality`, `RecoveryLog`, `RecoveryPush`,
  `ActivityTombstone`, `GarminDeletionCheck`), `health.0004_r17`, `planning.0009_r17`,
  `coaching.0012_r17` (also guesses `category` for existing facts),
  `reminders.0006_r17` — `Illness`, `DayDataDecision` (health), PlannedWorkout/StrengthSession
  `paused_by_illness`/`illness_return` (planning), MemoryFact `category, pinned, updated_at,
  edited` (coaching), ReminderSettings `recovery_ready` (reminders).
- Segmentation `ALGORITHM_VERSION` 1 → 2 (segmentation now reads the series chosen by
  the quality `use`). **After deploying run once:** `python manage.py derive` — it
  re-derives every activity still at v1 and stores its `ActivityQuality` (the
  20-minute `derive-anything-stale` beat would do the same in batches of 200). Caches
  keyed on the segmentation version (routes, fastest 1 km, heart stats) refresh by
  themselves. `python manage.py derive --all` forces everything.
- New Celery task `ingest.reimport_one` (garmin queue) — restart the workers. The daily
  slow sync makes one extra `get_activities(0, 100)` call (deletion check). No new env or
  dependencies.

## R18 — contract for full refresh, profile as the single source of truth, data_version, a coach that acts

Conventions as R10–R17 (paths under `/api/`, signed-in athlete, own rows only — another
athlete's id → 404; dates `YYYY-MM-DD`; datetimes ISO 8601 with offset; errors
`400 {detail}` unless noted). Additive except where marked **changed**. **Rohit's rule for
R18: user-controlled.** Memory and chat never change a setting silently — they propose,
the athlete confirms.

### Root causes fixed (prod: intraday 11:01 IST vs DailyMetrics 21:02 IST, stale steps)
1. **Intraday was only refreshed by the scheduled morning sync.** `ingest.sync_one` (beat,
   05:30 UTC = 11:00 IST) queued `sync_intraday_one`, but the manual/auto sync endpoint
   (`POST /garmin/sync/`) only queued the slow fetch — so every sync after the first of the
   day refreshed `DailyMetrics` and never `IntradayDay`. Every successful sync (legacy,
   full, auto) now refreshes intraday for today + yesterday.
2. **Today's totals were read from stale aggregates.** `IntradayDay.steps_total` (and the
   other aggregates) were computed only when intraday was stored, from the `DailyMetrics`
   of that moment; later wellness syncs updated `DailyMetrics` but not the aggregates, and
   `day_rows`/step history prefer the aggregate. Aggregates are now recomputed after every
   wellness write (today + yesterday), and a day's steps are the larger of Garmin's daily
   total and the 15-minute buckets.

### §A Full refresh = full sync

**`POST /garmin/sync/ {full: true}`** (Refresh button, pull-to-refresh, "Sync now") → **202**
```
{ job_id: str, deduped: bool,            # true: a job was already running/just started — that one is returned
  mode: "full",
  status: SyncStatus }
```
Runs on the garmin queue (one job per athlete at a time). Phases, in order:
`activities` (recent page, new runs downloaded) → `wellness` (daily summary, sleep, HRV,
stress, Body Battery, readiness … for today + yesterday, re-fetched and overwritten) →
`intraday` (today + yesterday, forced; then the slow-changing fetch if not done today) →
`derived` (segmentation/derivation of new runs inline, post-run work queued, achievements,
day aggregates; everything read-time — readiness, briefing, forecast, day summary, heart
stats, insights, wake plan — recomputes because `data_version` changed) → `done`.
Errors: 400 `{detail}` not connected; 429 `{detail, status}` breaker open (nothing queued);
409 `{detail}` when a legacy (non-job) sync holds the lock.
Dedupe: a second `full` POST while a job is queued/running, or within 60 s of the last job's
start, returns that job (`deduped: true`) — never a second job. Breaker checked before every
phase; the first 429 stops the job (`phase: "failed"`, part `status: "rate_limited"`) and
trips the breaker. Calls stay `GARMIN_SLOW_PAUSE_S` apart inside phases and between phases.

**`POST /garmin/sync/ {auto: true}`** (**changed**: runs the same job path, throttled): when
`auto_skip_reason` says no → 200 `{skipped: "recent"|"running"|"breaker_open"|
"not_connected"|"too_early", status}` (unchanged). Otherwise → 200
`{job_id, deduped: false, mode: "full"|"run_check", status}` (the R16 inline sync body keys
`imported/skipped/failed/errors/activity_ids/wellness_days` are no longer returned for
auto). `mode: "run_check"` (run-aware window, last full job < 30 min ago): only the activity
listing (1 call); if a new run arrives the job continues through wellness/intraday/derived.
Auto POSTs are no longer counted by the `garmin` 10/hour throttle (the server guard above
limits them).

**`POST /garmin/sync/ {}` / `{limit}`** (legacy inline sync): unchanged body + `status`, and
now also queues the intraday refresh (root cause 1) and returns `data_version`.

**`GET /sync/status/`** → R16 SyncStatus plus:
```
{ …R16 keys…,
  min_interval_s: 1800 | 300,           # changed: the current auto interval (300 in the run-aware window)
  auto_sync_due: bool,                  # changed: can_sync_now, ≥ 05:00 local, last sync and last
                                        #   attempt both older than min_interval_s (30 min, or 5 min run-aware)
  job_id: str|null,                     # the athlete's latest job (null: none in the last 2 days)
  phase: "idle"|"queued"|"activities"|"wellness"|"intraday"|"derived"|"done"|"failed",
  progress: int,                        # 0–100 (queued 0, activities 10, wellness 35, intraday 60, derived 85, done 100)
  started_at: datetime|null,
  finished_at: datetime|null,           # set when phase is done|failed
  error: str|null,
  parts: { activities: null | {status, imported: int, skipped: int, failed: int, activity_ids: [int]},
           wellness:   null | {status, days: int, written: int},
           intraday:   null | {status, days: int, calls: int},
           slow:       null | {status},                    # "not_due" when already done today
           derived:    null | {status, derived: int, achievements: int} },
                                        # part status: "ok"|"skipped"|"error"|"rate_limited"|"not_due"
  run_aware: { active: bool,            # a run is planned today, not arrived, now inside the window
               waiting_for_run: bool,   # same as active (UI: "Waiting for today's run…")
               workout_id: int|null, title: str|null,
               run_time: "HH:MM"|null, run_time_source: "workout"|"usual"|"alarm"|"history"|null,
               window_start: datetime|null,   # run time − 15 min
               window_end: datetime|null,     # run time + 3 h
               arrived: bool },               # a run activity for today is already here
  data_version: int }
```
Run-aware rule: from (run time − 15 min) to (run time + 3 h), while today's planned run
(not REST/STRENGTH, not done/skipped) has no run activity today, auto-sync is allowed every
5 min (`run_check` mode unless a full sync is due). Outside it: every 30 min. `running` is true
while a job is queued or running.

### §B Profile = single source of truth

**`GET/PATCH /athlete/`** gains
```
sleep_need_minutes: int|null,        # writable; 240–720; null = use Garmin's
usual_run_time: "HH:MM"|null,        # writable
loop_distance_km: float|null,        # writable; 0.1–50 (one lap of the athlete's usual loop)
injury_note: str,                    # writable; ≤ 200 chars ("" = none) — shown by injury watch
sleep_need: { minutes: int,          # read-only: the effective need used everywhere
              source: "user"|"garmin"|"default",   # override > Garmin (median of last 7 nights) > 8 h
              garmin_minutes: int|null,
              label: str },          # "7 h (set by you)" | "8 h (Garmin)" | "8 h (default)"
data_version: int                    # read-only
```
Effective sleep need (one helper, `apps.athletes.effective.sleep_need`) is used by: sleep
debt and tiles (`/health/sleep/`), wake planner + bedtime reminders (`/health/wake/…`),
readiness forecast levers, morning briefing, auto-adjust's sleep signal and the coach context.
- `GET /health/sleep/` gains `need: SleepNeed` (the object above); every night's `need_s` is the
  effective need (the override when set) and gains `garmin_need_s` (Garmin's value that night).
- Wake plan `need_source` gains `"user"`; `run.run_time_source` gains `"usual"` (athlete
  `usual_run_time`, preferred over the alarm's run time and history).
- `GET /health/injury/` gains `athlete_note: str` (= `injury_note`).

**Workout JSON** (everywhere) gains
```
distance_estimate: null | { km: float,           # run time at the middle of the easy pace band + walk time at 10:00/km
                            loops: float|null,   # km / loop_distance_km, 1 decimal (null without a loop distance)
                            loop_km: float|null }
```
null for REST/STRENGTH or a workout without steps.

**`data_version`** (per athlete, opaque increasing int):
- Bumped on every write to the athlete's data (settings, memory, data-review decisions,
  illness, workouts and edits, chat tool changes, journal, habits, every sync write) and on
  every successful mutating request (POST/PUT/PATCH/DELETE).
- Returned: header `X-Data-Version` on every authenticated `/api/` response; key
  `data_version` in every 2xx JSON-object body of a mutating request (lists / 204 → header
  only); in `GET /athlete/` and `GET /sync/status/`.
- Frontend: when a mutation (or a sync status poll) returns a `data_version` different from
  the last one seen → invalidate all athlete queries.
- Server caches keyed on it (plus the local date): insights, day summary, readiness
  forecast, wake plan, heart stats. AI summaries: `POST /insights/summary/` body and the
  briefing `ai` object gain `stale: bool` (data changed after the text was generated).

**Memory → settings (propose, never apply silently).** Fact JSON (`/memory/` all forms) gains
```
settings_proposal: null | { field: "sleep_need_minutes"|"usual_run_time"|"loop_distance_km"|
                                   "available_days"|"runs_per_week"|"long_run_day"|"injury_note",
                            label: str,               # "Sleep need"
                            value: int|str|float|object,   # in the field's API format
                            display: str,             # "7 h"
                            current: same type|null,
                            current_display: str,     # "8 h (Garmin)"
                            summary: str }            # "Sleep need: 8 h (Garmin) → 7 h"
```
null when nothing maps, or the setting already has that value. UI: "Apply to settings?".
**`POST /memory/{id}/apply/`** `{field}` (must equal the proposal's field) → 200
`{applied: true, field, before, after, display, data_version, fact: Fact}`; 400 `{detail}`
when the fact has no (or a different) proposal or the value fails validation (same rules as
PATCH /athlete/); 404 another athlete's fact.

### §C Coach acts on explicit requests

New chat tool:
```
update_profile(field, value, confirmed?)
  field: "sleep_need_minutes"|"usual_run_time"|"loop_distance_km"|"available_days"|
         "runs_per_week"|"long_run_day"|"injury_note"
  value: sleep_need_minutes → minutes (or hours ≤ 12, converted) | null (= Garmin's);
         usual_run_time "HH:MM"; loop_distance_km number; available_days [0–6 weekdays] or
         {"0".."6": bool}; runs_per_week 2–6 | null; long_run_day 0–6; injury_note str
```
Results: `{status: "needs_confirmation", field, label, current_display, display, summary,
warnings: [str], message}` (nothing saved) unless `confirmed: true` **and** the previous
assistant message in the thread asked to confirm the same field and value (server-enforced —
a same-turn self-confirmation is refused with needs_confirmation again);
`{status: "updated", field, before, after, display, summary, warnings, data_version}`;
`{status: "unchanged", …}`; `{error}`.

Chat message JSON (and the POST reply top level) gains
```
profile_changed: [{field, label, before_display, after_display, summary}]   # [] when none
```
and `needs_confirmation` may now be the profile variant
`{field, value, label, summary, increase_pct: null}` (alongside R16's workout/week variants).
UI: same "Yes, do it / No" buttons.

Coach behaviour (system prompt): the athlete is in charge — on an explicit change request
(plan, workout, settings) call the tool; warnings or needs_confirmation → explain the risk
briefly and ask "Do it anyway?"; never refuse outright. Increases still follow R16 (+20 %
direct, more → confirmation).

**Refusal guard** (server side, next to the R16 honesty guard): if the athlete's message is an
explicit change request ("make/change/set/increase … to 30 min", "move … to Sunday",
"set my sleep need to 7 h") and the reply declines it ("I can't / won't / wouldn't
recommend / let's keep …") without calling any change tool (edit_workout, edit_week,
move_workout, skip_workout, clear_day, update_profile, set_illness, recover_illness,
propose_plan — a needs_confirmation result counts as a call), the model is re-prompted once
to call the tool and present warnings + a confirmation instead. Logged and stored on
`ChatMessage.guard` (`{"refusal": {...}}`, not in the API).
