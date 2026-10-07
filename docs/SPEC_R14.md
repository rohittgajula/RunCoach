# R14 — Declutter everything, weather report + smart reschedule, calendar sync, self-experiments, goals, heart adaptation, admin page + Gemini (Google AI Studio)

Requested by Rohit 2026-10-07. Same rules as before (Python calculates, model interprets;
safety only easier; tenant isolation; health data to AI only as aggregates; private
habit never to AI). R10 design language.

## 1. Declutter (frontend, every section)
Rohit: "the app is a bit cluttered in all the sections". Principles:
- **Progressive disclosure**: each screen opens with a short summary (≤ 4–5 cards above
  the fold-equivalent); details live behind "See details ›" sheets or collapsed
  sections. No card shows more than ~3 facts before an expander.
- **One card per purpose**; merge overlapping ones; contextual cards appear only when
  actionable (and disappear once done/dismissed).
- **Today**: one hero card = greeting + readiness ring + today's session (+ adjusted
  chip) + one-line briefing focus; below: weather tile (compact), LOG NOW, fuel/water
  compact row. Conditional: review (24 h after a run, collapsible), mood (until
  answered), injury (only moderate/high), check-ins (when due). Everything else moves
  to Health/Plan. **Customise Today** (Me → Settings): toggle/reorder optional cards
  (saved on the athlete: `today_layout` list).
- **Health**: Overview = 3 rings + 4 key tiles + "What changed" (3 bullets) + links;
  other tiles behind "All metrics ›". Each section (Day, Fitness, Sleep, Habits,
  Progress, Guides) gets a short summary header and collapsible detail groups;
  reduce chip count by grouping: Overview · Day · Sleep · Fitness · Habits · Progress
  · More (Guides, Compare, Reports, Experiments, Goals, Heart).
- **Plan, Coach, Diet, Me**: same treatment (Diet: today ring + water + meals; trends
  behind "Trends ›"; Me: grouped list rows instead of many cards).
- Keep every feature reachable; nothing removed, only reorganised.

## 3. Weather report + weather-smart rescheduling
- Tapping the weather tile opens **Weather** (`/weather`): now (temp, feels-like,
  humidity, dew point, wind, UV, AQI/PM2.5 with plain meaning), hourly 24–48 h chart
  (feels-like, rain %, AQI lanes) with best run windows highlighted, 7-day daily
  forecast (min/max, rain, AQI where available), sunrise/sunset, hydration & food
  advice, "your runs this week vs the weather" list. Backend `GET /weather/report/`
  (Open-Meteo forecast 7 days + air quality; cached hourly; degrade gracefully).
- **Smart reschedule**: daily check (and on forecast refresh) of the next 3 days of
  planned runs: when a run day is forecast bad (feels-like ≥ 34 °C during all
  candidate windows, thunderstorm/heavy rain ≥ 70 %, AQI > 150) and another available
  non-run day in the same week is better, create a **suggestion** (never auto-move
  without consent unless setting "auto-apply weather swaps" is on): swap or move the
  session; respects long-run/hard spacing rules (reuse reflow/relayout helpers),
  re-syncs the watch. Today/Plan show "Weather: move Thu run to Fri? [Move] [Keep]".
  Endpoints: `GET /plan/weather-suggestions/`, `POST …/{id}/apply|dismiss/`.

## 5. Calendar sync (ICS)
- Private subscribe URL `/cal/{token}.ics` (unguessable token, revocable/regenerate in
  Me → Calendar sync) with planned workouts (title, duration, description with steps,
  location none), strength sessions, races; updates when the plan changes; ETag/
  Last-Modified; no health data beyond workout titles. "Add to Google Calendar" /
  "Add to Apple Calendar" (webcal://) buttons + instructions.

## 7. Self-experiments
- `Experiment(athlete, kind, title, start, end (7–42 days), rule json, status)` with
  templates: no alcohol, no caffeine after 14:00, no sugar, smoke-free, bed by 22:30,
  10k steps/day, custom (habit + limit). Daily adherence computed from logs
  (habits/caffeine/sleep/steps); baseline = same length before start. Result card at
  the end: adherence %, HRV, RHR, sleep score, stress, easy-pace HR, mood/energy
  before vs during, with n, non-causal wording; "keep it / stop" + share card.
  Active experiment shown as a slim progress chip on Today. Endpoints under
  `/experiments/`.

## 8. Long-term goals
- `Goal(athlete, kind: race_time|distance|weight|smoke_free_days|vo2max|resting_hr|
  weekly_km|custom, target, target_date?, start_value, status)`; progress from data,
  projected date (linear/trend-based, labelled estimate), milestones (25/50/75/100 %),
  badges hook. Health → More → Goals page + one-line goal chip on Overview.

## 9. Heart adaptation (Rohit's request: "I ran 5 min at 150 bpm on day 1 — I want to
see day by day how my heart is improving or adjusting")
- Per run (run segments only, warm-up excluded, steady parts): **HR at a reference
  pace** (pace band around his easy pace), **pace at a reference HR** (e.g. 150 bpm
  ±3), **efficiency** (speed ÷ HR), **aerobic decoupling** (pace:HR drift first vs
  second half), **HR recovery** (drop in the 60 s after a run segment ends → walk, and
  after the run if data), **time to settle** (how long until HR stabilises in a run
  block), **run duration at ≤ 150 bpm** (longest continuous run below a cap).
- Normalise for heat (feels-like at run time from weather history; flag hot runs) and
  terrain (elevation gain per km).
- `GET /health/heart/?range=` → per-run series + rolling 7-run trend + "since day 1"
  comparison (first runs vs latest: "Day 1: 5 min at 150 bpm. Now: 11 min at 150 bpm;
  at the same pace your HR is 9 bpm lower") + heat-adaptation view (hot vs cool runs
  over time) + plain sentences. UI: Health → More → **Heart** (also linked from
  Progress and Fitness): headline sentence, day-by-day chart (each run a dot, trend
  line), the four key numbers with (i), hot-day toggle.

## 14. Admin page + Google AI Studio (Gemini)
Staff-only (`is_staff`), `/admin-panel` in the app (not Django admin), hidden for others;
backend endpoints under `/api/admin/…` with IsAdminUser + tests that non-staff get 403.
- **Users & invites**: list users (name, joined, last active, Garmin linked, last sync,
  plan, AI spend this month); create/revoke invite codes; disable a user.
- **AI**: providers **OpenAI** (existing) and **Google AI Studio / Gemini** (new, via
  `GEMINI_API_KEY`; use Gemini's OpenAI-compatible endpoint
  `https://generativelanguage.googleapis.com/v1beta/openai/` through the existing
  client abstraction — chat completions + tool calling; verify streaming/tool support
  and fall back gracefully). Per tier (lite/fast/coach/deep) choose provider + model
  from a list (stored in DB `AIConfig`, env as default; admin can test a prompt).
  Price table per model (input/output per 1M tokens, editable) → cost per request in
  AIRequestLog (store provider, model, tokens in/out, cost, latency, ok/error).
  Stats: tokens & cost per day/month, per tier, per feature (operation), per user,
  per provider/model; error rate; budget per user (existing) editable.
- **System**: Garmin breaker state + per-user sync status; Celery queue lengths; last
  backups (local + R2 when configured) — via a read-only Kubernetes ServiceAccount for
  the backend (Role in namespace: get/list pods, jobs, cronjobs; ClusterRole: nodes +
  metrics.k8s.io read) — node CPU/memory/disk, pod status/restarts; app version (git
  sha). GCP trial: end date 2027-01-03 and credit from config (`GCP_TRIAL_END`,
  `GCP_CREDIT_INR`), days left.
- Secrets: `GEMINI_API_KEY` added by Rohit via a hidden prompt into prod.env
  (never echoed); feature hidden when missing.
