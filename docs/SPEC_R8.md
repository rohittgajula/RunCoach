# R8 — Runs per week, habits (quit smoking), progress comparison, weather

Requested by Rohit 2026-10-07. Same rules as before: Python calculates, the model
interprets; safety only ever makes training easier; tenant isolation; health data never
leaves except as aggregated numbers to the AI.

---

## A. Runs per week (setting)

Context: Rohit selected 6 days; the plan used 4 (beginner cap). He wants to choose.

- `Athlete.runs_per_week` (nullable int, 2–6; null = coach default). API also returns
  `runs_per_week_recommended` (= `run_day_limit()` for the active plan's baseline, or the
  profile baseline) and `runs_per_week_effective` = min(choice or recommended,
  available-day count, 6). **Always at least one rest day** (max 6).
- Generator: the week's planned running volume is unchanged; it is split across the chosen
  number of run days (`run_days()` spread). **Minimum session**: no run session shorter than
  15 min of total time — if splitting would go below, use fewer sessions for that week and
  say so in the response (`notes`). Hard-session rules unchanged.
- Changing `runs_per_week` (or `available_days`/`long_run_day` when the session count must
  change) **re-lays future weeks** of the active plan: weeks after today keep their weekly
  run volume and phase, sessions are regenerated with the new count, recorded adaptation
  factors (PlanAdjustment) are re-applied to their weeks, today/past/completed untouched,
  RACE fixed. Pure logic in `planning/` (extend `reflow.py` or a sibling), Django glue in
  `apps/planning/reflow.py`. Synced-to-watch workouts that change are re-sent, removed ones
  are removed (existing `garmin_sync` helpers). PATCH /api/athlete/ `plan_reflow` gains
  `regenerated: n` and `notes: [str]`.
- Settings: "Runs per week" stepper/segmented (2–6, "Coach: 4" hint, "Auto" option);
  helper text: "More runs = same total, shorter sessions. At least one rest day."

## B. Habits — smoking, alcohol, sugar (quit smoking)

### Data
- `HabitLog(athlete, kind: smoke|alcohol|sugar, at (aware dt), local_date, quantity float,
  note)` — smoke = cigarettes, alcohol = standard drinks, sugar = servings (chocolate,
  sweets, sugary drink). Index (athlete, kind, local_date).
- Athlete fields: `smoke_goal` (`quit|reduce|none`), `smoke_quit_date` (date, nullable),
  `smoke_baseline_per_day` (float, nullable), `cigarette_price` (₹, nullable),
  `alcohol_goal` / `sugar_goal` (`reduce|none`), `daily_limits` (json, optional).
- Included in account deletion; never sent to the AI except as the aggregates below.

### Endpoints
```
POST   /habits/logs/        {kind, quantity=1, at?, note?} → Log   (at defaults to now)
GET    /habits/logs/?kind=&start=&end=                    → [Log]
PATCH/DELETE /habits/logs/{id}/
GET    /habits/today/       → {date, counts: {smoke, alcohol, sugar}, last_at: {...}}
GET    /habits/summary/?range=4w|12w|6m
  → { range,
      smoke:   {series:[{date,count}], total, per_day_avg, trend_per_week,
                streak:{current_days, best_days}, since_quit:{days, cigarettes_avoided,
                money_saved}, milestones:[{label, reached:bool, at}]},
      alcohol: {series, total, per_week_avg, drink_days},
      sugar:   {series, total, per_day_avg},
      impact: [ {habit, metric, label, with_avg, without_avg, diff, diff_pct, n_with,
                 n_without, direction:"worse"|"better"|"no_clear_difference",
                 enough_data:bool} ],
      weekly: [ {week_start, cigarettes, drinks, sugar, hrv_avg, rhr_avg, sleep_score_avg,
                 easy_pace_s_per_km, efficiency} ],
      summary: {status:"none"|"ready", markdown, generated_at} }
POST   /habits/summary/?range=&refresh=1  → generate AI explanation (coach tier, cached/day)
```

### Impact analysis (pure `analysis/habits.py`)
- "Exposure night" = metrics dated the morning after a day with ≥1 log of that habit;
  "clean night" = after a day with none. Metrics (DailyMetrics): overnight HRV, resting HR,
  sleep score, body battery high, avg stress, sleep respiration. Run metric: runs on the day
  after exposure vs clean — HR at easy pace / efficiency factor (speed ÷ HR), HR drift.
- Report mean with vs without, n each; `enough_data` only when n ≥ 5 in both groups;
  direction uses a meaningful threshold (HRV ±5 %, RHR ±2 bpm, sleep score ±3, body
  battery ±5, stress ±3) else `no_clear_difference`. Dose view for alcohol: 1–2 vs 3+
  drinks when data allows. Never claim causation in copy: "on nights after…, your HRV was
  X lower on average (n=…)".
- Smoking milestones are general public-health timeline facts (20 min, 12 h, 24 h, 48 h,
  2 weeks, 1 month, 3 months, 1 year), shown as "typically", from quit date.

### Integrations
- Morning check-in: new signal `alcohol` — drinks logged yesterday ≥ 3 → `watch`, ≥ 5 →
  `bad`; never makes a session harder. Reason chip "3 drinks last night".
- Chat tool `log_habit(kind, quantity, at?)` so "had 2 beers at 9" or "smoked 3 today"
  logs it; system prompt gets today's/yesterday's counts and the quit streak.
- Insights focus rules: smoking days ↑ → "Smoke-free streak" focus; alcohol nights with
  lower HRV (enough_data) → focus item.

### UI
- Calendar today card + Insights: quick-log row 🚬 🍺 🍫 — tap = +1 now (toast with Undo),
  long-press/⋯ = sheet to set quantity/time/note. Today's counts shown on the buttons.
- Insights → **Habits** section: smoke-free streak (big number), cigarettes/day chart,
  drinks/week, sugar/day, "since you quit" (days, cigarettes avoided, ₹ saved, milestones
  list), **Impact** cards (only enough_data ones; others "keep logging — need 5 nights
  each"), AI summary with Generate/Refresh.
- Settings: Habits section (smoke goal quit/reduce, quit date, baseline/day, price per
  cigarette; alcohol/sugar goal).

## C. Progress comparison

`GET /progress/?window=1|5|10|20&sport=running`
- Compares the most recent `window` runs vs the `window` runs before them (window=1:
  last run vs the average of the previous 5). Metrics per group: run distance, total
  distance, run pace (run blocks), avg HR, max HR, HR at easy pace, efficiency factor
  (m/min per bpm), HR drift, cadence, run fraction, longest continuous run, time in Z2 %.
  Each: `{key, label, current, previous, delta, delta_pct, better: true|false|null, unit}`
  (direction-aware: lower pace = better, lower HR at same pace = better…).
- `distance_buckets`: same comparison for runs grouped by distance (<2 km, 2–5, 5–8, 8+)
  so like is compared with like.
- `bests`: fastest 1 km, longest run distance, longest continuous run, lowest HR at easy
  pace — with dates; flag new bests in the window.
- `series`: per-run points for charts (date, run_km, pace, avg_hr, efficiency, cadence).
- `focus`: deterministic "what to improve / what to check" items (e.g. HR drift rising →
  check hydration/heat; cadence flat <160 → drills; run fraction stalling → extend blocks).
- `POST /progress/review/?window=` → AI review {went_well[], improve[], check[], markdown},
  cached per window per day.
- UI: Insights → **Progress** card: segmented Last 1 · 5 · 10 · 20, metric table with
  current vs previous and green/red arrows, distance-bucket toggle, bests list, chart
  (pace & HR vs date, colour by distance), Review button.

## D. Weather → hydration, food, run timing

- Location: `Athlete.location_lat/lon` (rounded to 2 decimals, ~1 km), `location_name`,
  `location_source` (`runs|city|none`). Auto from the GPS start of the most recent
  running activity with a position (rounded); Settings city field overrides (geocode with
  Open-Meteo geocoding, no key). Reuse `apps/ingest/weather.py` where sensible.
- Fetch Open-Meteo forecast (hourly: temperature, apparent temperature, humidity, dew
  point, precipitation probability, wind, UV; daily max/min) and Open-Meteo air quality
  (PM2.5, US AQI). Cache per athlete-location per hour (Redis or DB). Garmin-style rate
  limits don't apply; still time out at 5 s and degrade gracefully (no weather ≠ error).
- Pure `analysis/weather_advice.py`:
  - Heat bands by apparent temp / dew point (e.g. dew point ≥ 24 °C or feels-like ≥ 32 °C
    = hot): pace slowdown guidance (%), "run by HR not pace", best run window (coolest +
    lowest AQI hour within 05:00–09:00 and 17:00–20:00 local).
  - Hydration: before 400–600 ml; during ml/h scaled by feels-like (cool 300–400, warm
    500–700, hot 700–900) for runs ≥ 45 min; electrolytes/sodium when hot or > 60 min;
    after: replace ~1.5× estimated loss.
  - Daily water target bonus: +500 ml when max feels-like ≥ 32 °C, +250 ml ≥ 28 °C.
  - Food: hot days → more fluids/salty snack, lighter pre-run meal; cold → nothing special.
  - AQI: > 100 caution (easy only), > 150 shorten/indoors, > 200 → morning check-in
    signal `air` = bad. Rain/thunderstorm → caution note.
- `GET /weather/today/` → `{location_name, source, now:{temp, feels_like, humidity,
  dew_point, aqi, pm25, condition}, hourly:[next 24h], best_window:{start,end,reason},
  advisories:[{level, text}], hydration:{before_ml, during_ml_per_h, after_note,
  electrolytes:bool}, food:[str], daily_water_bonus_ml}`.
- Integrations: Calendar today card shows a weather chip (temp/feels-like/AQI + best
  window); workout sheet "Weather & hydration" block; Diet water target includes the bonus
  and a hot-day food tip; workout fueling text uses the forecast; morning check-in gains
  `heat` (watch) and `air` (watch/bad) signals — easier only.

## E. Not changed
Deploy, auth, Garmin push rules. Account deletion must include HabitLog and location.
