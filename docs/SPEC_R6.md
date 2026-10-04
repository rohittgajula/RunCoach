# R6 — history, actual-vs-planned, month calendar, Insights, more Garmin

Addendum to [SPEC.md](SPEC.md). Same rules: Python calculates, the model interprets;
safety only ever makes things easier; tenant isolation everywhere.

Requested by Rohit on 2026-10-04 after first real use. His account (athlete 3) has 18
activities 2 Jul – 24 Aug 2026: 7 runs 9–24 Aug (run/walk, cadence 116–150), walks, a
ride, strength. The plan treated him as having **no history**.

---

## 1. Use real history (bug)

- **Cause**: `baseline_for` looks back `BASELINE_WEEKS` (4) only; last run was 24 Aug, so
  6 weeks later the window is empty → beginner defaults.
- **Fix**: look back up to 16 weeks for the most recent *block* of running. Take the best
  week from that block, then apply a **detraining factor** for the gap since the last
  run: ≤ 14 days → 1.0, 15–28 → 0.85, 29–56 → 0.7, > 56 → 0.5, never below the
  beginner default. Longest continuous run is reduced the same way. Record in
  `summary`: `baseline_source: "history"`, `last_run_date`, `gap_days`,
  `detraining_factor`, and a warning sentence ("Your last run was 6 weeks ago, so this
  starts at ~70 % of your best August week.").
- **Sync depth**: first sync (no activities yet) pages back 12 months
  (`get_activities(start, 100)` pages until older than the cutoff); later syncs fetch
  until an already-known activity id is hit (max 100). Same idempotency as now.
- Chat context gets `history_summary`: totals since first activity, last run date, gap
  days, best week, longest continuous run ever + date, per-month run km.

## 2. Unplanned runs count

- A run on a day with no planned workout (or a rest day) is a normal activity: shows on
  the calendar, counts in week totals (`actual_s`, `actual_load`), Fitness/Fatigue/Form,
  and the plan's next weekly adaptation. Calendar item gets `unplanned: true` and the card
  shows an "Extra" tag.
- Auto-link rule stays: a run on a day **with** a planned run workout links to it.
- **Weekly adaptation**: when an active plan exists, `adapt_week(athlete)` runs after
  each sync (Celery, idempotent per ISO week) and on Monday via beat: it compares last
  week's actual running minutes/load to planned and, deterministically, (a) if actual
  < 60 % of planned → repeat the current week's volume next week instead of progressing;
  (b) if actual > 130 % → do NOT increase further (cap at plan); (c) otherwise follow the
  plan. Only future, not-completed workouts change. Logged as a `PlanAdjustment` row
  (`week_start, reason, factor, created_at`) shown in plan detail.

## 3. Completed workout → actual vs planned

`GET /workouts/{id}/` (and calendar `Workout`) gains, when `completed_activity_id` is set:

```
actual: {
  activity_id, duration_s, distance_m, run_distance_m, walk_distance_m, run_fraction,
  longest_run_s, avg_hr, max_hr, avg_cadence_spm, avg_pace_s_per_km (run blocks only),
  time_in_zone: {Z1..Z5: seconds} | null, steps: [Step] | null     # segments as steps
}
compliance: {                                   # pure Python, analysis/compliance.py
  score: 0-100,
  checks: [{key, label, status: "hit"|"close"|"missed", planned, actual, note}],
  # keys: duration, run_time, easy_effort (time in target zone ≥ 70 %), hr_ceiling
  # (no run block over athlete.hr_ceiling), continuous_block (long runs), intervals
  # (count of hard blocks vs planned)
}
review: {status: "none"|"ready", summary_md, went_well: [str], to_improve: [str]} 
```
- `review` is an AI interpretation (coach tier, cached in AIAnalysis keyed by input
  hash) of the compliance + metrics + journal — generated lazily by
  `POST /workouts/{id}/review/` and stored; GET returns it once present.
- A run that isn't linked (unplanned) gets the same `actual` block via
  `GET /activities/{id}/` → `ActivityCard` + `review`.

## 4. Month calendar

`GET /calendar/month/?month=YYYY-MM` →
```
{ month, today, days: [{date, planned: {kind, title, duration_s}|null,
  status: "done"|"missed"|"partial"|"planned"|"rest"|"extra"|"today"|null,
  activities: [{id, sport, duration_s, distance_m}]}],
  totals: {planned_s, actual_s, runs_done, runs_planned, runs_missed} }
```
Status rules: past planned run with a linked activity → `done` (`partial` if compliance
score < 60); past planned run without one → `missed`; run on an unplanned day →
`extra`; future planned → `planned`.

UI: Calendar header gets a **List / Month** segmented switch. Month view = 7-column grid
(Mon first), ‹ month › navigation, each day a cell with the date number and a dot/ring:
green done, amber partial, red missed, blue outline planned, purple extra; today
outlined. Tap a day → the same detail sheet as the list (workout or activity). Monthly
totals line under the grid ("9 of 12 runs · 6h 40m").

## 5. Insights tab (new, 5th tab: Calendar · Chat · Diet · Insights · Profile)

`GET /insights/?range=4w|12w|6m` → all computed in Python:

```
{
  readiness: {score 0-100|null, label, drivers: [str], source: "garmin"|"computed"},
  hrv: {last_night_ms, weekly_avg_ms, baseline_low, baseline_high, status: "balanced"|
        "unbalanced"|"low"|"poor"|null, series: [{date, ms}]},
  sleep: {avg_s, avg_score, series: [{date, s, score}]},
  resting_hr: {current, trend_bpm_per_week, series},
  body_battery / stress: {avg, series},
  respiration: {avg_rpm, sleep_avg_rpm, series},          # "breathing"
  vo2max: {value, series} | null, race_predictions: {5k_s, 10k_s, half_s} | null,
  running: {
    runs, run_km, run_fraction_trend: series, longest_run_trend: series,
    easy_pace_trend: series (pace at Z2 HR — aerobic efficiency),
    cadence: {avg, trend, target: 160-175, note},
    hr_drift_avg, pace_cv_avg,
    form: {ground_contact_ms, vertical_oscillation_cm, stride_length_m} | null
  },
  load: {fitness, fatigue, form, status, acwr},
  focus: [ {title, why, how} ]          # 3 deterministic "what to improve" rules
  summary: {status: "none"|"ready", markdown}   # AI paragraph, cached per day
}
```
`focus` rules (deterministic): cadence < 155 → "Shorter, quicker steps"; easy runs with
> 30 % time above Z2 → "Slow the easy days down"; run_fraction rising slowly →
"Extend run blocks by 30–60 s"; HRV below baseline 3+ days → "Recovery first"; sleep <
7 h avg → "Sleep"; gap > 7 days → "Consistency"; respiration elevated vs baseline →
"Breathing / possible illness — easy only".
`POST /insights/summary/` generates the AI overview ("Are you running well?") from the
payload above — never inventing numbers.

UI: cards top to bottom — Readiness ring + drivers; "How you're running" (run fraction,
longest continuous run, easy-pace efficiency, cadence with target band); "Recovery"
(HRV with baseline band, RHR, sleep, body battery, stress); "Breathing" (respiration
trend); VO2max + race predictions; "Focus next" (3 items); AI overview card with a
"Generate" button and timestamp. Every card tappable → full chart sheet (reuse
MetricChart + RangeSwitch).

## 6. Pull everything useful from Garmin

Extend `apps/ingest/garmin_wellness.py` (daily, 28 days on first sync, then since last)
and `DailyMetrics` (new nullable fields): `hrv_weekly_avg`, `hrv_baseline_low/high`,
`hrv_status`, `sleep_score`, `sleep_deep_s/light_s/rem_s/awake_s`, `body_battery_high/low`,
`stress_avg`, `respiration_avg`, `respiration_sleep_avg`, `spo2_avg`, `training_readiness`,
`vo2max_running`, `steps`, `intensity_minutes`, `race_pred_5k_s/10k_s/half_s/marathon_s`.
Each call wrapped individually — one endpoint failing must not lose the rest (log +
skip). Keep the rate-limit circuit breaker.
Per activity from the FIT file (already parsed per-second): avg/max cadence (run blocks),
`avg_stride_length_m`, `avg_vertical_oscillation_cm`, `avg_ground_contact_ms`,
`training_effect_aerobic/anaerobic` (from Garmin activity summary), `avg_respiration`.
Add to `ActivityMetrics` (nullable) and expose in `actual` + activity detail. Re-derive
existing activities with the management command (`derive`/`reingest`).

## 7. Small fixes

- Step and title durations round to whole minutes; run/walk blocks to the nearest 0.5
  min (30 s) **in the generator output**, then everything else derives from that. No
  "Run 3.7m" anywhere. Labels: "Run 3:30", "Walk 3:00".
- Detail sheet steps: group consecutive identical run+walk pairs as "3 × (Run 3:30 ·
  Walk 3:00)".
