# R10 — New look + more Garmin data + 6 new features

Requested by Rohit 2026-10-07 ("add all", approved the design in docs/design-r10/).
Same rules: Python calculates, the model interprets; safety only makes training easier;
tenant isolation; health data reaches the AI only as aggregates; the private habit
never reaches the AI. Builds on R9 (Insights sections, habits report, progress, guides).

The approved mockups are `docs/design-r10/*.dc.html` (static HTML; open in a browser):
Main = design language, Today, Health (overview), Fitness, Sleep. Screens not drawn
(Habits, Progress, Weekly report, Guides, Compare, Me) follow the same language.

---

## A. Redesign (frontend)

### Navigation — still 5 bottom tabs
**Today · Plan · Coach · Health · Diet.**
- Today = the current Calendar tab's "today" content redesigned (greeting + avatar,
  readiness ring, today's workout hero card in Running blue with a step bar, weather
  card with hourly bar chart + best window + hydration trio, LOG NOW tiles, fuel
  progress bars, this-week ring, tomorrow forecast, weekly report card on Mondays).
- Plan = the month/week calendar + plan timeline (the old Calendar minus today card).
- Coach = Chat. Diet = Diet restyled.
- Health = the old Insights, sections as horizontally scrollable chips:
  **Overview · Fitness · Sleep · Habits · Progress · Guides** (`/health/...`; redirect
  old `/insights/*` and `/calendar` routes). "Compare any two" is a card/link at the
  bottom of Overview (`/health/compare`). Range switch top-right of the header.
- Profile is no longer a tab: avatar button (top-right of Today and every page header)
  opens **Me** (`/me`): profile, settings, shoes, reminders, badges, account.

### Design language (match docs/design-r10/Main.dc.html)
- Font: Plus Jakarta Sans (self-host via `@fontsource/plus-jakarta-sans`, 400–800),
  tabular numbers for all figures.
- Ground #F4F5F7, card #FFF, radius 20 (tiles 18, controls 12–14), soft two-layer
  shadow, ink #101418, muted #5B6573. Proper dark palette with the same roles.
- Colour by topic (never for good/bad): Running #2F6BFF, Recovery #7A5AF8, Sleep #0E9F9A,
  Habits #F2A516, Fuel #F26B3A. Better/worse: green #12A150 / red #E5533D, always with
  ▲/▼ shape too. Status pills: Improving / Worsening / Steady / Need more data.
- Charts: one shared grammar — trend line + shaded "your normal" band, rounded bars with
  highlighted selection + dark rounded tooltip, score rings (topic colour), "then → now"
  rows, coloured-dot bullet findings, caption line under every chart, delta chip in
  every chart header. Reuse/upgrade R9's ChartFrame/ChartTip.
- Every screen works at 375–400 px, tap targets ≥ 44 px, reduced-motion respected.

## B. More Garmin data (backend ingest)

Use the existing unofficial `garminconnect` client (check which methods 0.3.10 really
has; upgrade the pin only if needed and safe), the existing rate-limit circuit breaker
and the garmin queue. Slow-changing data is fetched at most once a day per athlete;
anything the watch doesn't provide is stored as null and hidden in the UI.

1. **Fitness trend**: daily VO2max (already), endurance score, fitness age, race
   predictions (already) → history endpoint.
2. **Training status + load focus**: status label (productive/maintaining/…),
   low aerobic / high aerobic / anaerobic load with target ranges.
3. **Lactate threshold**: HR + pace; when present, recompute the athlete's HR zones
   from it (record source + date; never make easy zones harder than current without
   the safety rule; show "Zones updated").
4. **Sleep details**: bedtime/wake time, sleep need, restlessness, overnight SpO2 —
   enables bedtime regularity (SD of bedtime), sleep debt (need − actual, 7-day sum).
5. **Running form trends**: per-run cadence, ground contact, vertical oscillation,
   stride length (already stored per activity) → series endpoint.
6. **Personal records**: Garmin PRs (1K, 1 mile, 5K, 10K, half, longest run) plus our
   own computed bests; "new PR" flag with date.
7. **Body composition / weight** (if logged in Garmin): weight, body fat %, trend;
   Diet uses latest weight when present.
8. **Gear / shoes**: Garmin gear list + distance; local fallback: user-defined shoes
   with activities auto-assigned to the default shoe; replace reminder at a
   configurable km (default 700).

Endpoints (all GET, tenant-scoped): `/health/fitness/?range=`, `/health/sleep/?range=`,
`/health/form/?range=`, `/health/records/`, `/health/body/?range=`,
`/gear/` (+ POST/PATCH for local shoes), `/health/training-status/`.

## C. New features

9. **Lung recovery tracker** (Habits section, needs smoke quit date): from the quit
   date, trends of sleeping breathing rate, overnight SpO2, resting HR and HR at easy
   pace vs the 14 days before quitting; milestone timeline (R8 milestones). Non-causal
   wording. Not shown when no quit date.
10. **Weekly report card**: every Monday 06:00 local (Celery beat) build last week's
    report: runs done vs planned, km, time in zones, PRs, HRV/RHR/sleep vs previous week,
    habits vs previous week, 3 bullets went well / to improve, one goal for this week
    (deterministic), optional AI paragraph (coach tier, cached). `GET /reports/weekly/
    ?week=YYYY-MM-DD` and list of past reports. Shown on Today on Mondays + Health.
11. **Compare any two**: `GET /health/compare/?x=metric&y=metric&range=&lag=0|1`
    → paired points, Spearman ρ, n, plain-language sentence ("Nights with more sleep
    tended to be followed by lower easy-pace HR, ρ=−0.48, n=22"). Metric catalogue:
    daily wellness metrics, habit counts (not private unless enabled; never to AI),
    run metrics (by run date). UI: two pickers, scatter + trend line, sentence.
12. **Reminders** (PWA web push): morning check-in, habit log reminder (evening),
    "best time to run" from weather, weekly report ready. Backend: VAPID web push
    (`pywebpush`), subscription model, per-reminder toggles + times in Me; Celery beat
    sends at local time. VAPID keys come from env (`VAPID_PUBLIC_KEY`,
    `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`); feature hides itself when missing. iOS needs
    the PWA installed to the home screen — say so in the UI.
13. **Achievements & streaks**: deterministic badges (smoke-free 1/3/7/14/30/90 days,
    consistent weeks 2/4/8/12, first 5K, new PRs, run streaks, sleep 7h+ streaks),
    earned date stored, toast + Me → Badges grid (earned vs locked with progress).
14. **Tomorrow's readiness forecast**: deterministic estimate from today's load, recent
    HRV trend, sleep debt, habits logged today, with "what could raise it" levers
    (bedtime, no alcohol); clearly labelled estimate. On Today and Health overview.

## D. Order of work
Backend B+C first-pass in one agent; frontend redesign A + new screens in another,
using these field names. Deviations → docs/API_NOTES.md "R10". Ship only after full
tests, build, and screenshots at phone size.
