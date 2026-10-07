# R11 — Daytime stats ("Day"), move/breathing reminders, hydration log, run maps

Requested by Rohit 2026-10-07. Same rules as R8–R10 (Python calculates, the model
interprets; tenant isolation; health data to AI only as aggregates; private habit never
to AI; safety only easier). Follow the R10 design language (docs/design-r10/,
Kit.tsx, r10.css, ChartFrame/ChartTip).

## A. Intraday Garmin data (backend)

Fetch per day with the existing unofficial client, garmin queue, circuit breaker and
spacing (as R10 slow fetch): all-day heart rate (`get_heart_rates`), stress + body
battery timeline (`get_stress_data` / `get_body_battery`), steps in 15-min buckets
(`get_steps_data`), plus daily summary fields already present (steps goal, intensity
minutes, floors, active/sedentary seconds from `get_user_summary` if available). Verify
real method names/payloads in garminconnect 0.3.10.
- When: after each successful sync for today + yesterday (yesterday finalises), and a
  light backfill command for the last 30 days (spaced, refuses while breaker open).
- Storage: one row per athlete-day (`IntradayDay`) with compact arrays (e.g. HR every
  2 min, stress every 3 min, body battery every 3–15 min, steps per 15 min) as JSON of
  `[minute_of_day, value]` in athlete-local time, plus derived daily aggregates columns.
  Keep size small (no raw payload duplication beyond what's needed). Covered by account
  deletion.

## B. Analysis (pure, `analysis/day.py` etc.)
1. **Timeline** for a date: series HR, stress, body battery, steps/15 min; markers:
   runs (activity start/end), sleep window, habit logs (non-private unless enabled;
   private never shown unless enabled), naps if detectable.
2. **Steps**: total, adaptive goal (median of last 28 days ×1.05, clamped 6k–15k, or
   Garmin goal if set — say which), trend, streak of goal days, most/least active hour,
   run days vs rest days avg.
3. **Active vs sedentary**: minutes sedentary/active/intense (from Garmin when given,
   else from steps buckets: <50 steps/15 min sedentary), longest sedentary stretch
   while awake with clock times.
4. **Stress**: minutes rest/low/medium/high (Garmin bands 0–25/26–50/51–75/76–100),
   peak window of the day, weekday pattern over the range ("peaks 11 am–1 pm on
   weekdays"), high-stress streaks ≥30 min.
5. **Body battery**: charged/drained amounts, top drain/charge events (sleep, runs,
   stress stretches, rest), value at wake and at bedtime.
6. **Daytime HR**: awake min/max/avg, avg awake HR trend over weeks.
7. **Daily score card**: deterministic end-of-day summary (sentence + 3 bullets +
   1–2 tips for tomorrow).
8. **Day → night → run**: add day metrics (steps, active min, stress avg/high min,
   body battery at bedtime, awake HR) to the R10 Compare catalogue, and a fixed card
   "Busy/stressful days vs that night's sleep/HRV and next run" (n thresholds, non-causal).
- Endpoints: `GET /health/day/?date=` (timeline + all above for the day),
  `GET /health/day/trends/?range=` (steps/stress/active/awake HR/body battery trends,
  weekday patterns, day→night card), compare catalogue extended.

## C. Reminders (extend R10 reminders)
10. **Move reminder**: after 60–90 min (setting) sedentary within user-chosen hours,
    max N per day, not during/just after a run, quiet hours respected. Needs near-real-
    time data: evaluate on the existing intraday sync cadence; if Garmin data is too
    delayed, say in the UI that it's based on the last sync time. Never spam.
11. **Breathing break**: stress ≥ 51 for 30+ min (latest data) → nudge with deep link to
    the breathing guide (`/health/guides?g=breathing`). Same limits.
Both off by default, in Me → Reminders with hours/threshold settings.

## D. Hydration log
12. `WaterLog(athlete, at, local_date, ml)` + endpoints (POST quick add 250/500 ml,
    custom; list today; delete). Target = existing daily water target incl. weather
    bonus. Today's Fuel card water bar becomes real; Diet shows water too; quick-add
    buttons. Reminder option "drink water" (off by default, every 2 h in hours).

## E. Run maps
- Each run detail (workout/activity sheet) gets a **map**: route polyline from stored
  records lat/lon, coloured by pace / HR / run-walk segments (toggle), km markers,
  start/finish markers, tap a point → pace/HR at that point, linked elevation profile
  under it. Use Leaflet (npm) with OpenStreetMap-compatible tiles with proper
  attribution; update the app's CSP (find where it is set: nginx/Traefik/meta) to allow
  the tile host only. Lazy-load the map code (route-level chunk) so the main bundle
  doesn't grow.
- **Privacy**: setting "Hide start/end on maps" (default ON: trim first/last 200 m).
- Backend: `GET /activities/{id}/route/` → simplified polyline (Douglas–Peucker, ≤ 800
  points) with per-point pace/HR/segment type/elevation/distance; tenant-scoped; cached.
- Progress section: small "Your routes" heat-map-ish overlay of the last 20 runs
  (optional if time permits).

## F. Health → "Day" section
New chip **Day** between Overview and Fitness (`/health/day`, date picker ← today →):
timeline chart (synchronised HR / stress / body battery / steps lanes, markers),
score card, steps card (goal ring + trend), active vs sedentary bar, stress breakdown
stacked bar + peak window, body battery drains/charges list, awake HR card,
day→night→run card. Today screen gets a compact "Today so far" row (steps ring, stress
now, body battery now) linking to Day.

Ship only after full tests, build, phone-size screenshots; deviations in API_NOTES "R11".
