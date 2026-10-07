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
