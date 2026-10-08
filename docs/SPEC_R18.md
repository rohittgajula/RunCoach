# R18 — Everything dynamic: full refresh, profile as the single source of truth, coach that acts

Requested by Rohit 2026-10-08 ("if something changes it should impact all related
stats; if I refresh it should sync ALL data with Garmin, not some").

Observed in prod: DailyMetrics re-synced at 21:02 IST but IntradayDay last updated 11:01
IST (Day screen "data up to 7:15 AM"); sleep_need = Garmin 8 h although Rohit told the coach
and memory "7 h"; coach refused "17 → 30 min" instead of warning + asking to confirm;
Rohit's browser showed the pre-R17 Memory sheet (stale PWA bundle).

## A. Full refresh = full sync
- `POST /api/garmin/sync/ {full: true}` (manual Refresh / pull-to-refresh / "Sync now"):
  activities (recent page), daily summary + sleep + HRV + stress + body battery for
  today and yesterday (force re-fetch, overwrite), intraday for today + yesterday
  (force), slow-changing data if due, then recompute everything derived (segmentation
  for new runs, reviews, recovery, readiness, briefing, forecast, day summary, heart
  stats, achievements). Respect breaker + spacing; dedupe concurrent requests; return
  a job id. `GET /api/sync/status/` reports `phase` (activities|wellness|intraday|
  derived|done), `progress`, `finished_at`, per-part results.
- Bug: intraday must refresh on every sync (not only the first of the day); daily
  totals for today must be re-fetched (steps were stale). Tests.
- Auto-sync (R16) uses the same full path but throttled (30 min; 5 min while a planned
  run for today hasn't arrived — "run-aware": poll every 5 min from planned/usual run
  time −15 min until +3 h or the run arrives).

## B. Profile = single source of truth; every change ripples
- Athlete settings (new where missing): `sleep_need_minutes` (override; null = Garmin),
  `usual_run_time`, `loop_distance_km` (preferred loop), others already present
  (available days, runs/week, HR zones, goals). All calculations read the effective
  value (override > Garmin > default) via one helper: sleep debt, sleep tiles, wake
  planner, bedtime reminders, readiness/forecast levers, briefing, reports, compare.
- Change propagation: any settings change, memory edit, data-review decision, illness,
  workout edit, new sync bumps a per-athlete "data version"; all cached computations
  (insights, day summary, briefing, forecast, wake plan, heart stats, reports cache,
  AI summaries marked stale) key on it, so the next read recomputes. Frontend
  invalidates all athlete queries when a mutation returns `data_version` changed.
- Memory → settings: when a memory fact (chat or manual) states something that maps to
  a setting (sleep need, usual run time, loop distance, available days, runs/week,
  long-run day, injuries → injury watch note), propose the setting change: chat tool
  `update_profile(field, value)` (coach asks confirmation in chat), and the Memory page
  shows "Apply to settings?" on such facts. No silent changes.
- Loop distance: workout cards show estimated km and "≈ N loops" for time-based
  sessions; the coach can propose distance-based steps when asked.

## C. Coach acts on explicit requests
- System prompt: the athlete is in charge. When they explicitly ask to change their
  plan/workout/settings, call the tool. If the tool returns warnings or
  needs_confirmation, explain the risk briefly and ask "Do it anyway?" (Yes/No) — never
  refuse outright. Increases still follow R16 (+20 % direct, more → confirmation).
- Honesty guard (R16) stays. Add a "refusal guard": if the reply declines an explicit
  change request without calling a tool, re-prompt once to call the tool and present
  warnings + confirmation instead.

## D. App always up to date + refresh UX
- Service worker: new version detection → small "Update available · Reload" banner
  (and auto-reload on next app open if idle); never stay on an old bundle > 1 open.
- Refresh button in the header of Today and Health (and pull-to-refresh on mobile)
  → full sync with a progress pill ("Syncing activities… sleep… day data…"), then all
  queries refresh. Today shows "Waiting for today's run…" (run-aware) when relevant.
- Settings: Sleep need (hours, "Use Garmin's: 8 h" default), usual run time, loop
  distance. Sleep screens show "Your target: 7 h (set by you)".
