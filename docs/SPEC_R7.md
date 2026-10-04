# R7 — Morning check-in, post-run check-in, easy-day pace guard (+ send to Garmin)

Addendum to [SPEC.md](SPEC.md) / [SPEC_R6.md](SPEC_R6.md). Same rules: Python decides,
the model explains; safety rules only ever make a session easier; tenant isolation.

---

## 1. Morning check-in ("Rest or train?")

### Backend
Reuse the pure `planning/readiness.py` (`WellnessSnapshot`, `assess`, `apply`) and
`apps/planning/plan_services.snapshot_for` — they already encode sleep / HRV / RHR /
body battery / Garmin training readiness / journal pain+illness rules from MyRunAnalizer.
Adapt them to the persisted `PlannedWorkout` (do not resurrect the regenerate-on-read
plan): new pure `planning/checkin.py` → `decide(snapshot, workout_summary) -> Verdict`.

`GET /today/` →
```
{ date,
  verdict: "go" | "easy" | "swap" | "rest" | "no_plan",
     # go   = as planned
     # easy = same duration, all hard/stride blocks become easy, HR cap lowered 5 bpm
     # swap = replace with 20–30 min brisk walk (or shorten to 50 % run/walk if only mildly flagged)
     # rest = pain / illness reported, or several red flags
  headline: "Go as planned" | "Keep it easy today" | "Swap for a walk" | "Rest today",
  reasons: [{signal: "sleep"|"hrv"|"rhr"|"body_battery"|"readiness"|"pain"|"illness"|"load"|"stress",
             status: "good"|"watch"|"bad", label, value, baseline}],
  signals_missing: [str],                 # e.g. ["hrv"] when no data last night
  workout: Workout | null,                # as planned
  adjusted: Workout-like | null,          # what the verdict changes it to (not saved)
  applied: bool,                          # athlete accepted the change today
  explanation: {status: "none"|"ready", text}   # one-line AI "why", cached per day
}
POST /today/apply/   → applies `adjusted` to today's PlannedWorkout (status stays planned,
                       `adjusted_by="checkin"`, original kept in `original_steps`), returns /today/
POST /today/explain/ → generates the one-line explanation (lite tier), cached per day.
```
Rules (deterministic, in `decide`): pain or illness journal in last 3 days → `rest`;
≥ 2 "bad" signals → `swap`; 1 "bad" or ≥ 2 "watch" → `easy`; else `go`. Signals vs the
athlete's own 28-day baseline: HRV below Garmin baseline_low = bad; sleep < 6 h = bad,
< 7 h = watch; RHR ≥ baseline + 7 = bad, + 4 = watch; body battery high < 30 = bad,
< 50 = watch; Garmin training readiness < 25 bad, < 50 watch; ACWR > 1.5 = watch;
yesterday's post-run RPE ≥ 8 = watch. Missing data never counts as bad — it is listed
in `signals_missing`. Rest-day verdict when no workout: `no_plan` with a recovery note
and the daily movement suggestion ("easy 20-min walk").

Run automatically: after the morning wellness sync (Celery beat 07:00 athlete-local is
fine as a daily task that syncs wellness for connected athletes, then computes).
Never auto-apply — the athlete taps "Use this".

### Frontend
Calendar (list view): a **check-in card pinned above today** (and at the top of the
Calendar when today is in view): verdict pill (green go / blue easy / amber swap /
red rest), headline, 3–5 signal chips (Sleep 6h 10m · watch, HRV 42 ms · good …),
one-line explanation (lazy-generated), and buttons **Use this** (POST /today/apply/)
/ **Keep plan**. When applied, today's workout card shows an "Adjusted" tag and the
adjusted bar. Missing signals shown as a subtle "No HRV last night" line.
Also show a compact version at the top of Insights.

## 2. Post-run check-in

### Backend
Journal already exists (`apps/journal`, `JournalEntry` with `rpe`, `pain_reported`,
extraction). Add a structured path that does NOT need the AI:

`GET /checkins/pending/` → activities (running/walking, last 7 days) without a journal
entry: `[{activity: ActivityCard, workout_id|null}]`.
`POST /activities/{id}/checkin/ {rpe: 1-10, legs: "fresh"|"ok"|"heavy"|"sore",
breathing: "easy"|"ok"|"hard", pain: {where: str, level: 1-10}|null, note: str}` →
creates a `JournalEntry(source=run_log, activity=…, rpe, pain_reported=bool(pain),
extracted={structured fields})` directly (note text still goes through the existing
extractor asynchronously if non-empty), marks `Activity.journalled`. Returns the entry.
`POST /activities/{id}/checkin/skip/ {reason}` → existing skip semantics.
Readiness (`decide`) and the workout review/compliance read these (RPE vs planned
effort: easy session with RPE ≥ 7 → check "effort" missed, note "felt harder than an
easy run should").

### Frontend
- After sync, if pending check-ins exist: a **"How did it feel?" sheet** opens once per
  activity (and a badge/card on Calendar until done). Fields: RPE slider 1–10 with
  labels (1-2 very easy … 9-10 max), legs chips, breathing chips, "Any pain?" toggle →
  where (chips: foot, ankle, shin, calf, knee, hip, back, other) + level slider, optional
  note. Done / Skip. Must take ~10 s.
- Activity sheet shows the check-in summary; missing → "Add check-in" button.

## 3. Easy-day pace guard + send to Garmin

### Backend
- Every easy/long/run-walk `PlannedWorkout` already has HR bands per step. Add
  `guard: {hr_max, pace_min_s, pace_max_s, cadence_target}` on the Workout JSON: hr_max =
  top of Z2 (athlete zones) or `athlete.hr_ceiling` fallback; pace band = easy band.
- Compliance (R6) gets an `easy_effort` check that is already specified; add per-run
  `time_above_cap_s` and `%` to `actual`, and the Insights focus rule already exists.
- **Send to Garmin**: `POST /workouts/{id}/garmin/` → builds a Garmin running workout
  from `steps` (warmup/run/walk/cooldown; each step with a HEART_RATE target range = the
  step's hr band; walk steps no target; repeats as a repeat group when steps repeat),
  uploads with the pinned garminconnect 0.3.10 (`upload_running_workout` or
  `upload_workout` — check what the installed version expects), then
  `schedule_workout(workout_id, date)`. Store `garmin_workout_id` + `garmin_synced_at` on
  the PlannedWorkout. Idempotent: if already uploaded and steps unchanged → no-op; if
  steps changed (check-in applied / moved) → delete old Garmin workout, upload new.
  `DELETE /workouts/{id}/garmin/` → unschedule + delete.
  `POST /plans/active/garmin/ {days: 7}` → send the next N days in one go.
  Runs on the `garmin` queue (rate-limit + circuit breaker apply). Errors → 502/503
  with `{detail}`; never partial silent success — return per-workout results.
- Payload builder is pure (`planning/garmin_workout.py`) and unit-tested against a
  fixture of the expected JSON shape. **No live uploads in tests or by agents** — the
  first real upload is done by Rohit from the UI.

### Frontend
- Workout detail sheet: **"Easy-day guard"** box on easy/long/run-walk workouts:
  "Keep heart rate under 145 bpm · pace 10:00–10:45 /km · cadence ~160", with a short
  why ("Easy days build the engine; going harder makes tomorrow worse").
- Button **Send to Garmin** (shows "On your watch ✓ · synced 08:12" after; "Update on
  watch" if changed; remove option in ⋮). Calendar week header ⋮ → "Send this week to
  Garmin".
- Completed workout: "Time above cap: 6 min (22 %)" line in actual-vs-planned, red if
  > 20 %.
