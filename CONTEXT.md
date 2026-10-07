# RunCoach — living context

> Claude keeps this current. If it contradicts the code, the code wins and this is stale.

Last updated: **2026-10-07** · Status: **R0–R4 built; R6 backend built (history baseline, adaptation, month calendar, Insights, more Garmin); R7 backend built (morning check-in, post-run check-in, easy-day guard, send to Garmin — no live upload yet) — R5 polish next** (see [docs/SPEC.md](docs/SPEC.md) § 6). Deviations from the API contract: [docs/API_NOTES.md](docs/API_NOTES.md).

## Origin

Started 2026-10-04 after Rohit tried **RestOrTrain** (Play Store `com.restortrain`, an AI
coach for cyclists). Its UI — three tabs, a calendar of workout bars, a chat that proposes
plans you accept, a profile of a few honest numbers — was "simple and on point" in a way
MyRunAnalizer's screens were not. RunCoach is that shape, **focused on running**, plus a
**Diet** tab RestOrTrain doesn't have.

It is a new repo, not a redesign. The proven backend of `~/Desktop/MyRunAnalizer` was
**copied** (Garmin ingest, run/walk segmentation, plan generator, mode resolver,
readiness, journal, AI client). Its `CONTEXT.md` § "Hard-won facts" applies here in full —
read it before touching Garmin, dates, or the AI client.

## Decided (2026-10-04)

| Question | Answer |
|---|---|
| Codebase | New repo `~/Desktop/RunCoach`; copy proven parts, rebuild the UI. |
| Platform | PWA (React + Vite), installable from Chrome on Android. Play Store wrap later. |
| Theme | Light and dark, following the system, with a manual override. |
| Diet scope | Daily targets from training · AI meal logging (photo/text) · run fueling · weight-trend tie-in. |
| Plans | **Persisted** now (MyRunAnalizer regenerated on every read). Chat proposes → athlete accepts → workouts materialise. |
| Git | Repo `github.com/rohittgajula/RunCoach` (**public** — never commit secrets or personal data). Since 2026-10-04 Rohit has Claude commit and push. Branches: `development` (work) and `production` (CI/CD deploys only from here). |

## What changed from MyRunAnalizer

- Plans, phases and workouts are rows, so they can be proposed, accepted, moved, skipped.
- Chat is a tool-using agent (propose plan, move/skip workouts, log meals, memory) rather
  than a journal-only endpoint.
- New: Fitness / Fatigue / Form (42/7-day EWMA of the custom load) and training-status bands.
- New: `nutrition/` pure package and `apps/diet`.
- Kept: segmentation first, "only ever easier" safety rules, model tiers in env.

## Running

`docker compose up -d` → frontend :5174, API :8001, Postgres :5434, Redis :6381.

## Verified end-to-end (2026-10-04, phone viewport, real model calls)

Login → onboarding → chat "build a plan for 10k" → proposal card → accept → calendar
fills with workouts → Guide opens a chat with the workout attached and a step-by-step
answer incl. fueling. Weight entry + history sheet. Diet targets for a rest day.
Backend suite: 661 passing (R6 + R7 backend + deploy hardening + plan re-flow).

## Deploy hardening (2026-10-04, docs/DEPLOY.md §1–2)

Env contract + startup guard (`config/security.py`), WhiteNoise, `REGISTRATION_MODE`
with `InviteCode` (admin "Generate code"), per-IP throttles via `CF-Connecting-IP`
(`config/middleware.py`; XFF ignored), signed 1 h meal photo URLs (`apps/diet/media.py`),
`DELETE /api/auth/me/` (`apps/athletes/deletion.py`), `/api/health/live/`. Found on the
way: `ChatThrottle`/`GarminThrottle`/`AIThrottle` on function views had never throttled
anything — fixed with `FixedScopeThrottle`.

## Known follow-ups

- Workouts have no time of day, so fueling "before" gives both the normal and the
  early-morning option.
- No auto-estimated metric entries yet (e.g. threshold pace from runs).
- Chat can't take image attachments directly; meal photos go through Diet → Log meal.
- Not yet exercised in the UI: meal photo logging, Review on a synced activity
  (needs Garmin connected), training-status chart with real history.
- Main bundle is ~790 kB; code-split Recharts.
- Celery workers don't hot-reload — restart `worker` after changing tasks.

## Training days are availability (2026-10-04)

- Ticking N days never means N runs. The generator caps run days (4 while baseline
  < 15 km/week, else 5), spreads them for the largest minimum gap, and makes the other
  available days optional walks (`planning/generator.py: run_days`).
- Plans are stored. Since 2026-10-07 saving new days (or a new long-run day) in
  Settings **re-flows** the active plan: future workouts move onto the new days, nothing
  is regenerated, extra short easy sessions are dropped if the days no longer fit, and
  workouts already on the watch are replaced there (`planning/reflow.py`,
  `apps/planning/reflow.py`, `apps/planning/garmin_sync.py`; API_NOTES § Plan re-flow).
  Settings shows "Upcoming workouts moved to your new days (…)". The old **Rebuild
  plan** offer is gone from the UI; `POST /api/plans/active/rebuild/` remains.
- Rohit's 7-day selection on 2026-10-04 was never saved (no PATCH reached the server);
  his profile was still Mon/Wed/Fri/Sat.
