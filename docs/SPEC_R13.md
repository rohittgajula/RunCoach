# R13 — Adaptive coaching, race day, injury watch, strength, briefings, quit support, reports, sharing, export, speed, zero-downtime, off-site backups

Requested by Rohit 2026-10-07 (items 1,2,3,4,6,7,8,9,10,11,12,15,16,17,18 of the list).
Same rules as before: Python calculates, the model interprets; **safety only ever makes
training easier** (no auto-change may increase load beyond the plan's own progression);
tenant isolation; health data to AI only as aggregates; private habit never to AI.
R10 design language; plain-language (i) explanations on every new metric (glossary.ts).

## 1. Auto-adjusting plan (after each run)
- After a run is ingested and matched (existing compliance/actual-vs-planned), evaluate:
  RPE/post-run check-in, HR drift, avg HR vs target zone, completion %, readiness,
  sleep debt, habits last night, injury watch flags.
- Deterministic rules in `planning/adapt.py` (pure): make the next 1–2 sessions easier
  (shorten 10–25 %, convert to easy/run-walk, swap order, add rest) when strain signals;
  allow at most +5 % duration on the next easy session when ≥3 consecutive runs were
  easy-and-good — and never above the plan's own weekly volume. Never touch completed
  or past sessions, RACE, or sessions already edited by the user.
- Every change stored as `PlanAdjustment` (existing model or extend) with a plain
  reason; re-sync changed workouts to Garmin via existing garmin_sync helpers.
- User setting "Auto-adjust plan" (default ON) + Undo on each change. Today/Plan show a
  chip "Adjusted: shortened to 20 min — your HR ran 8 bpm high yesterday".

## 2. Race-day planner
- For a race in Races: per-km pacing plan (even/negative split from predicted time +
  goal), fueling/hydration schedule (by duration + weather forecast when ≤ 7 days),
  warm-up routine, taper checklist for the final 10 days (plan already tapers — show
  checklist items: sleep, carbs, kit, route, bib, shoes ≤ 600 km & worn in),
  race-morning timeline (wake, breakfast, arrive, warm-up). `GET /races/{id}/plan/`.
- UI: race card → "Race plan" sheet; printable/shareable (share card #12).

## 3. Injury watch
- Daily deterministic risk flags (`analysis/injury.py`): weekly km ramp > 10 % (and
  ACWR > 1.3), long-run share > 40 % of week, cadence drop ≥ 5 spm vs 4-week baseline,
  ground-contact balance asymmetry > 2 % (if Garmin provides GCT balance — store it if
  present in activity data), shoe past replace threshold, pain reports.
- "Anything hurting?" quick check (post-run check-in + optional daily): body-map
  buttons (foot, ankle, shin, calf, knee, hamstring, quad, hip, lower back) × side ×
  severity 1–3 → `PainReport`. Pain ≥ 2 on the same spot 2 days → morning check-in
  signal `pain` (watch/bad, easier only) and plan auto-adjust (easier only) + guidance
  "see a physio if it persists" (no diagnosis).
- `GET /health/injury/` → {risk: low|moderate|high, flags[{kind, text, since}],
  pains[...]}; card on Health Overview + Today when not low.

## 4. Strength plan in the calendar
- Optional setting "Strength sessions per week" (0–3, default 0 → suggest 2).
  Generator places 20-min strength sessions on non-run days (or after easy runs if no
  free day), never the day before a long/hard run; exercises from the Guides set,
  progressing every 2 weeks (reps/sets). Calendar items type `strength`; "Send to
  watch" using existing Garmin strength workout push if the client supports it (the
  repo/MCP has create_strength_workout knowledge — check garminconnect 0.3.10 for an
  upload endpoint for strength workouts; if unsupported, hide the button). Mark done
  manually or auto from a Garmin strength activity.

## 6. Daily morning briefing
- Built at the athlete's wake time (wake planner / first sync after 4 am): readiness,
  today's session (+ any auto-adjust), weather window + hydration, fuel target, one
  focus, injury/habit note. Deterministic content + optional short AI phrasing (lite
  tier, cached daily, aggregates only). Push notification (off by default, Me →
  Reminders) + Today top card "Good morning" (dismissible). `GET /briefing/today/`.

## 7. Post-run coach review
- Auto after each run ingest: compare with similar past runs (same type ± distance
  bucket): pace, HR at pace, drift, cadence, run fraction; went well / to improve /
  next time (deterministic bullets) + optional AI paragraph (coach tier, cached,
  aggregates only). Shown in the run sheet and as a Today card for 24 h; push
  "Run reviewed" (off by default). `GET /activities/{id}/review/`.

## 8. Quit-smoking support
- `CravingLog(athlete, at, intensity 1–5, trigger enum [coffee, alcohol, stress,
  after_meal, boredom, social, work_break, morning, other], place, mood 1–5,
  smoked bool, note)`. Pattern analysis: top triggers, hours, places; % cravings
  resisted; trend. "Craving now" button (Today LOG NOW ⋯, Habits page) → logs craving
  and opens a 3-min breathing pacer (Guides breathing) with a timer, then asks
  "Did you smoke?" (if yes, also log a cigarette).
- Savings goal: name + price ("New shoes ₹6,000") → progress from money saved since
  quit date (R8 since_quit) with ETA. Badges hook (R10 achievements): cravings resisted.

## 9. Caffeine log
- Habit kind `caffeine` (cups; types coffee/tea/energy via note or subtype field) with
  quick-log tile option (off by default, enable in Settings → Habits). Impact vs sleep
  (late caffeine after 14:00 → sleep score/deep sleep/latency) using the R9 report
  machinery; Compare catalogue entry.

## 10. Mood & energy check-in
- `MoodLog(athlete, local_date, mood 1–5, energy 1–5, note)` one per day (editable),
  asked inside the morning check-in (two 5-face rows) and on Today if missing. Compare
  catalogue entries; weekly/monthly report lines; never to AI except averages.

## 11. Monthly health report
- Like the weekly report, per calendar month (built on the 1st at 06:00 local): runs,
  km, PRs, VO2max/fitness age change, HRV/RHR/sleep vs previous month, habits
  (smoke-free days, drinks, sugar, caffeine), mood/energy averages, weight change,
  injury flags, 3 went well / 3 to improve / 1 goal. Optional AI paragraph. Health →
  Reports list gets Weekly | Monthly tabs. `GET /reports/monthly/?month=YYYY-MM`.

## 12. Share cards
- Client-side rendered images (canvas/SVG → PNG via `navigator.share` with files where
  supported, else open the image in a new view with "long-press to save") for: a run
  (map thumbnail without endpoints, distance, time, pace, HR), a week, a badge/
  milestone, smoke-free days. Never include health details beyond what the card shows;
  preview before sharing.

## 15. Data export
- `POST /export/` → builds a ZIP (CSV per table: activities, laps/segments summary,
  daily wellness, intraday daily aggregates, habits, cravings, mood, water, meals,
  weights, plans/workouts, reports; plus a JSON with athlete settings) as a Celery task;
  `GET /export/latest/` → status + one-time download link (expires 24 h, served via the
  backend with auth, not public). Max 1 export/hour. Me → Account → "Export my data".

## 16. Faster first load (frontend)
- Route-level code splitting (React.lazy) for every tab and heavy sheets (charts,
  guides, maps already lazy, chat markdown), vendor chunking, preload Today. Target
  main JS < 350 kB (report before/after). Keep PWA precache sensible.

## 17. Zero-downtime deploys (deploy/k8s)
- Backend/frontend Deployments: `maxUnavailable: 0, maxSurge: 1`, readiness probes
  (backend /api/health/, frontend /), `preStop` sleep 10 s + `terminationGracePeriodSeconds`
  30 so Traefik drops the old pod before it stops; gunicorn graceful timeout. Verify
  with kubeconform in CI.

## 18. Off-site backups (Cloudflare R2)
- Code path already exists (`runcoach-r2` secret, backup job uploads when configured).
  Verify it end-to-end with a test target (lifecycle: keep 14 daily + 8 weekly), add a
  restore script/doc `deploy/RESTORE.md`. **Needs Rohit**: create R2 bucket + API token
  (UI steps), then `deploy/secrets/r2.env` + push-secrets. Scheduled with him after
  office.
