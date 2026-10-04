# RunCoach — spec

A running-first AI coach with a **RestOrTrain-style UI**: four tabs — **Calendar · Chat ·
Diet · Profile** — and almost nothing else. Everything the athlete does starts from one of
those four screens or from a chat.

Built on the proven backend of `~/Desktop/MyRunAnalizer` (copied, not imported). Read its
`CONTEXT.md` § "Hard-won facts" before touching Garmin, dates or the AI client.

Rules carried over unchanged:

> **Python calculates. The model interprets.** Paces, loads, plan structure, calorie
> targets, fueling grams, safety gates: deterministic Python. The LLM explains, converses,
> proposes *through tools that call Python*, and estimates meal contents from a photo/text
> (the one thing only it can do — always shown as an editable estimate).

> **"Distance" means distance run.** Segmentation (cadence ≥ threshold) stays first.

> **Readiness and diet safety rules only ever make things easier / safer.** No deficit on
> long or hard days, no plan progression after reported pain.

Claude never runs git in this repo. Rohit owns git.

---

## 1. Screens (frontend)

PWA, React 19 + TS + Vite + TanStack Query + Recharts. Light **and** dark, following the
system (`prefers-color-scheme`). Mobile-first, max content width 560px centred on desktop.

### Visual language (taken from the RestOrTrain screenshots)

- Off-white ground (`#f7f7fb` light / `#0b0b0f` dark), white rounded cards
  (`radius 20px`, soft shadow light / 1px border dark), generous padding.
- Bold large headings (28–32px), muted grey secondary text, system font.
- Round "chip" icon buttons in the header (settings gear, chat list, new chat, refresh).
- Bottom tab bar: icon + label, active tab gets a pill background.
- **Workout bar**: a strip of blocks, width ∝ step duration, height ∝ intensity. Easy =
  light blue, moderate = deeper blue, hard/strides = red/pink, walk = grey, rest gap = none.
  Same component in calendar cards, chat attachments and workout detail.
- Black pill primary buttons ("Guide", "Review").
- Phase pill on workouts (Base = blue, Build = green, Peak = orange, Taper = purple,
  Recovery = grey).
- Charts: single blue line with gradient fill; range switch `3 months · 6 months · 1 year`.

### Tabs

**Calendar** (default tab)
- Vertical scroll of days, left column `Mon / 5`, today highlighted with a dark tile.
- Past days show synced activities (card: sport icon, name, "Garmin Instinct 2x via
  Garmin", workout bar if available else grey bar, Duration, Load, **Review** button).
- Future days show planned workouts (card: 🏃 Plan, workout bar, title, phase pill,
  Duration, Load, **Guide** button). Days without anything: "Rest" / "Recovery day" card.
- Week header between weeks: `Oct 5 – Oct 11`, total planned time + load, collapse chevron.
- Opens scrolled to today; infinite scroll both ways (fetch ±14 days at a time).
- Header: refresh (Garmin sync) left, settings right.
- Tap a card → **Workout / Activity detail sheet** (bottom sheet): bar, steps list with
  targets (pace band + HR band), purpose, fueling (before/during/after), buttons
  Guide / Move / Skip. Activity sheet: run/walk truth (run km, walk km, longest
  continuous run), splits, HR, Review.
- **Guide** → creates a chat with the workout attached and the message "How do I execute
  this workout?" and switches to Chat. **Review** → same with the activity and
  "Review this activity".

**Chat**
- Header: chat-list button + new-chat button left, settings right.
- Messages: user bubbles right (grey), assistant full-width markdown. Attachments render
  as cards above the user bubble (workout card with bar, activity card).
- Assistant messages may contain a **Plan Proposal card**: `PLAN PROPOSAL`, name,
  "4 phases", goal text, phase timeline (circle + line, dates, name, description), and
  Accept / Decline buttons. Line above it: "The proposal is not saved until you accept it."
- Status line while waiting: "Thinking…" → replaced by the answer.
- Composer pinned above the tab bar: "Ask anything", `+` (attach photo → goes to meal log
  or chat image), send button.
- Chat list (full-screen sheet): title + time, ⋮ menu (rename, delete), new chat.

**Diet** (new — not in RestOrTrain)
- Date switcher at top (‹ Today ›).
- **Targets card**: big kcal ring (eaten / target), three macro bars (carbs, protein,
  fat: eaten / target g), water target. One-line rationale ("Long run day — carbs up to
  6 g/kg").
- **Fuel your run card** for the day's planned workout(s): Before / During / After rows
  with concrete grams & timing.
- **Meals list** grouped Breakfast / Lunch / Snack / Dinner: description, kcal, macros,
  photo thumbnail, "AI estimate" tag. Tap → edit items/amounts. Swipe/⋮ delete.
- **Log meal** FAB / button → sheet: take/choose photo and/or type text ("2 dosa, sambar,
  chai with sugar"), meal type, time → AI estimate shown for confirmation, edit, save.
- **Balance vs weight card**: 3m/6m/1y chart of 7-day avg intake − target vs weight
  trend; text "Avg −320 kcal/day ≈ −0.3 kg/week predicted, −0.2 kg/week actual".

**Profile**
- Header: logo/title, settings gear.
- **Athlete card**: grid — Threshold Pace (min/km), Weight (kg), Easy pace band | HRV (ms),
  RHR (bpm), Sleep (h). Each metric tappable → **metric history sheet** (chart with
  range switch + list of entries with `Current` badge, source "Manual input" /
  "Garmin" / "Estimated", `+` to add an entry, `?` help).
- **Training Status** card (label + mini line) and **Fitness** card (number + mini area).
  Tap → full sheet with chart. Training Status chart has coloured bands:
  Detraining (> +20), Fresh (+5…+20), Maintaining (−10…+5), Gaining Fitness (−30…−10),
  Overtraining Risk (< −30); "About" + "Zones & tips" text below. Fitness sheet: line,
  "About Fitness", "How to use it". A dropdown in the sheet header switches between
  Fitness / Fatigue / Training Status.
- **Active plan card**: name, "4 phases", timeline of phases (current one expanded with
  description and "Starts tomorrow" / "Week 2 of 4"), "2 more phases" collapsed row.
  Tap → plan detail (all phases, all weeks).
- **Races** card: list, add/edit (A race toggle).
- **Memory** card → sheet: "RunCoach remembers key facts from your chats", list of facts
  with delete, `+` to add one manually, empty state "No memories yet".

**Settings** (gear, full-screen sheet): Garmin connect/disconnect/sync status, profile
fields (name, sex, birth date, height, timezone, available days, long-run day, HR max/rest,
diet goal: maintain/lose/gain + rate), theme override (system/light/dark), install app,
logout.

Auth screens (login/register) and a short onboarding (name → Garmin connect → first
chat "Build a plan for me to run 10k.") reuse the MyRunAnalizer flow, restyled.

---

## 2. Data model (backend additions)

Existing apps keep their models: `athletes.Athlete`, `ingest.*`, `activities.*`,
`journal.JournalEntry`, `coaching.AIRequestLog/AIAnalysis`, `planning.Race`.

### athletes.Athlete — new fields
`sex` (`male|female|null`), `height_cm`, `diet_goal` (`maintain|lose|gain`, default
maintain), `diet_rate_kg_per_week` (float, default 0.25, clamp 0–0.75),
`threshold_pace_s` (nullable; current value mirrored from MetricEntry for speed).

### athletes.MetricEntry
`athlete, kind (weight|threshold_pace|resting_hr|max_hr), value float, recorded_at
datetime, source (manual|garmin|estimated)`. "Current" = latest by recorded_at.
Writing a weight/threshold_pace entry updates the mirrored Athlete field.

### planning.TrainingPlan
`athlete, race (FK nullable), name, goal (text), status (proposed|active|archived|declined),
generator_version, summary (json: warnings, peak km, etc.), created_at, accepted_at,
chat_message (FK nullable)`. At most one `active` per athlete (accepting archives the
previous one and deletes its future, not-completed workouts).

### planning.PlanPhase
`plan, order, name, kind (base|build|peak|taper|recovery|race), start, end, description`.
Phases group the generator's weeks: consecutive weeks with the same generator phase
merge into one PlanPhase. Names/descriptions written by the AI when proposing
(validated: must keep dates and count unchanged); deterministic fallback names exist.

### planning.PlannedWorkout
`athlete, plan, phase (nullable), date, title, kind (generator SessionKind),
duration_s, load, steps (json), description, purpose, target_zone, fueling (json),
status (planned|completed|skipped), completed_activity (FK nullable), moved_from (date
nullable), created_at`. Materialised from the generator on accept. A synced activity on
the same date auto-links → `completed`.

`steps` item: `{kind: warmup|run|walk|stride|recovery|cooldown|interval,
duration_s, intensity: walk|easy|moderate|hard, label, pace_min_s, pace_max_s, hr_min,
hr_max}` — repeats are flattened (the bar draws every block).

Load for planned workouts uses the same `analysis/load.py` formula as actuals, so planned
and actual are comparable.

### coaching.ChatThread / ChatMessage
Thread: `athlete, title, created_at, updated_at`.
Message: `thread, role (user|assistant|tool), content (markdown), attachments (json list:
{type: workout|activity|plan_proposal|meal|image, id}), status (pending|done|error),
tool_calls (json, for audit), created_at`.

### coaching.MemoryFact
`athlete, text, source (chat|manual), source_message (FK nullable), created_at`.
Extracted by a lite-tier call after each assistant reply ("durable facts about the
athlete: injuries, schedule constraints, preferences, goals"), de-duplicated against
existing facts. Injected into every chat system prompt.

### diet.Meal
`athlete, eaten_at (datetime), local_date, meal_type (breakfast|lunch|dinner|snack),
description, photo (ImageField, nullable), items (json list: {name, quantity, kcal,
carbs_g, protein_g, fat_g}), kcal, carbs_g, protein_g, fat_g (totals, recomputed from
items on save), source (ai_photo|ai_text|manual), ai_confidence (low|medium|high|null),
created_at`.

---

## 3. Deterministic calculators (pure Python, no Django)

### `analysis/fitness.py`
- Daily load series from activities (existing `session_load`).
- Fitness = 42-day EWMA, Fatigue = 7-day EWMA, Form = Fitness − Fatigue.
- `status(form)` → `detraining (>20) | fresh (5..20] | maintaining [-10..5] |
  gaining (-30..-10) | overtraining (<-30)`.
- Needs ≥ 14 days of history to label; else `insufficient_data`.

### `nutrition/targets.py` (new package, pure)
- BMR Mifflin–St Jeor (needs weight, height, age, sex; if sex missing use the average of
  the two formulas; if height/age missing fall back to 22 kcal/kg).
- Non-exercise: BMR × 1.35.
- Exercise kcal: completed activity calories from Garmin when present; else planned
  running ≈ `1.0 × kg × km` (km from duration ÷ planned pace), walking ≈ `0.5 × kg × km`.
- Goal adjustment: lose → −`rate × 7700 / 7` kcal/day capped at −500; gain → +same capped
  +400. **Never any deficit on a day with a LONG / INTERVALS / TEMPO / RACE workout or the
  day after a long run** (rule only ever removes the deficit).
- Carbs g/kg: rest 3, easy ≤ 45 min 4, easy > 45 min 5, long/tempo/intervals 6,
  long ≥ 90 min 7, race day 8. Protein 1.6 g/kg (1.8 when losing). Fat = remainder,
  floor 0.8 g/kg (if floor breaks the total, total rises — never cut fat below floor).
- Water: 35 ml/kg + 600 ml per planned hour of running.
- Returns targets + a one-line rationale string built from the rules that fired.

### `nutrition/fueling.py` (pure)
Per workout, from duration, intensity and time of day:
- **Before**: < 45 min easy → "optional: banana / toast 30–60 min before";
  otherwise 1–1.5 g/kg carbs 2–3 h before, or 30 g carbs 30–60 min before if early
  morning. Always 300–500 ml water.
- **During**: < 60 min → water only; 60–90 → 30 g carbs/h; > 90 → 45–60 g/h + sodium
  300–600 mg/h. Concrete examples (gel, dates, banana).
- **After**: within 60 min — protein 20–30 g + carbs 1 g/kg (long/hard) or a normal meal
  (easy); rehydrate 1.5× fluid lost (estimate 0.8 L/h) .

### `nutrition/balance.py` (pure)
7-day rolling intake − target, predicted kg/week = avg balance × 7 / 7700, actual from
weight entries' linear trend over the same window. Only shown when ≥ 5 logged days in
the last 7 (else "log more days to see this").

---

## 4. Chat — tools the model can call

The chat runs as a tool-use loop (OpenAI client already in `coaching/client.py`; add a
`chat_with_tools` beside `complete`). System prompt = coach persona + athlete profile +
memory facts + last 6 weeks summary (minutes/week, longest run, run fraction, best 1 km,
threshold pace) + current plan/phase + today/tomorrow workouts + diet day summary.

Tools (all implemented in Python, all scoped to the athlete):

| tool | does |
|---|---|
| `get_training_summary(weeks)` | weekly minutes, load, run km, longest continuous run |
| `get_activity(id)` | segmented metrics, splits, HR, journal |
| `get_workout(id)` / `get_workouts(start,end)` | planned workouts with steps |
| `propose_plan(race_name, race_date, distance_km, is_target, available_days?, long_run_day?, phase_names_and_descriptions?)` | runs the deterministic generator, saves a `proposed` TrainingPlan with phases + workouts, returns its id → assistant message gets a `plan_proposal` attachment. The model may only supply names/descriptions; dates/volumes are the generator's. |
| `move_workout(id, new_date)` / `skip_workout(id, reason)` / `clear_day(date, reason)` | "Had a big night out, need a day off" → clears today, logs a journal entry |
| `log_journal(text, applies_to_date)` | existing journal extraction → readiness |
| `get_diet_day(date)` | targets, logged, fueling |
| `log_meal(description, meal_type, eaten_at)` | text meal → AI estimate → Meal |
| `add_memory(text)` | explicit "remember that…" |

Before asking a plan question the coach asks only what it can't derive (race date, how
many days/week, injuries) — exactly like the RestOrTrain welcome message.

Guardrails: max 6 tool iterations per turn; every call logged in AIRequestLog; monthly
budget check from existing `_spent_this_month`; on AIUnavailable the message gets
`status=error` and a friendly retry text — never a 500.

---

## 5. API contract (all JSON, under `/api/`, JWT auth as today)

Existing endpoints stay (auth, athlete, garmin/*, wellness, activities, races, journal).

```
GET  /profile/summary/
  → { athlete: {display_name, threshold_pace_s, weight_kg, easy_pace_min, easy_pace_max},
      wellness: {hrv_ms, resting_hr, sleep_s, date} | null,
      fitness: {value, fatigue, form, status, spark: [number]} ,   # spark = last 42 days fitness
      status_spark: [number],                                       # last 42 days form
      active_plan: PlanSummary | null,
      memory_count: number }

GET  /metrics/fitness/?range=3m|6m|1y
  → { series: [{date, fitness, fatigue, form}], current: {fitness, fatigue, form, status} }
GET  /metrics/entries/?kind=weight|threshold_pace|resting_hr|max_hr&range=3m|6m|1y
  → { kind, current: Entry|null, entries: [Entry] }   Entry = {id, value, recorded_at, source}
POST /metrics/entries/          {kind, value, recorded_at?}  → Entry
DELETE /metrics/entries/{id}/

GET  /plans/?status=            → [PlanSummary]
GET  /plans/active/             → Plan | 404
GET  /plans/{id}/               → Plan
POST /plans/{id}/accept/        → Plan        (archives previous active, materialises)
POST /plans/{id}/decline/       → Plan
  PlanSummary = {id, name, goal, status, race: Race|null, phase_count, start, end,
                 current_phase_id, phases: [Phase]}
  Phase = {id, order, name, kind, start, end, description}
  Plan = PlanSummary + {summary: {...}, weeks: [{start, end, planned_minutes, planned_load, phase_id}]}

GET  /calendar/?start=YYYY-MM-DD&end=YYYY-MM-DD   (max 62 days)
  → { today, days: [{date, items: [CalItem], rest: "Rest"|"Recovery day"|null}],
      weeks: [{start, end, planned_s, planned_load, actual_s, actual_load}] }
  CalItem = {type: "workout", workout: Workout} | {type: "activity", activity: ActivityCard}
  Workout = {id, date, title, kind, phase: {id, name, kind}|null, duration_s, load,
             steps: [Step], description, purpose, target_zone, fueling: Fueling,
             status, completed_activity_id}
  Step = {kind, duration_s, intensity, label, pace_min_s, pace_max_s, hr_min, hr_max}
  Fueling = {before: string, during: string, after: string, carbs_g_during_per_h: number|null}
  ActivityCard = {id, name, sport, device, start, duration_s, distance_m, load,
                  run_distance_m, walk_distance_m, run_fraction, longest_run_s,
                  steps: [Step] | null, journalled, reviewed_thread_id|null}

GET    /workouts/{id}/           → Workout
PATCH  /workouts/{id}/          {date?, status?}  → Workout
POST   /workouts/{id}/guide/     → {thread_id}     (creates thread + first exchange)
POST   /activities/{id}/review/  → {thread_id}

GET    /chat/threads/                     → [{id, title, updated_at}]
POST   /chat/threads/        {title?}     → Thread
PATCH  /chat/threads/{id}/   {title}      → Thread
DELETE /chat/threads/{id}/
GET    /chat/threads/{id}/messages/       → [Message]
POST   /chat/threads/{id}/messages/  {content, attachments?: [{type, id}]}
  → {user: Message, assistant: Message}       (synchronous; may take 5–30 s)
  Message = {id, role, content, attachments: [Attachment], status, created_at}
  Attachment = {type: "workout", workout: Workout} | {type: "activity", activity: ActivityCard}
             | {type: "plan_proposal", plan: PlanSummary} | {type: "meal", meal: Meal}

GET    /memory/            → [{id, text, source, created_at}]
POST   /memory/   {text}   → Fact
DELETE /memory/{id}/

GET    /diet/day/?date=YYYY-MM-DD
  → { date, targets: {kcal, carbs_g, protein_g, fat_g, water_ml, rationale},
      eaten: {kcal, carbs_g, protein_g, fat_g},
      burn: {bmr, non_exercise, exercise, exercise_source: "garmin"|"planned"|"none"},
      meals: [Meal], fueling: [{workout_id, title, ...Fueling}],
      missing_profile: [string] }        # e.g. ["height_cm","sex"] → UI nudges to Settings
POST   /diet/meals/estimate/   multipart {text?, photo?, meal_type?}
  → {description, items, kcal, carbs_g, protein_g, fat_g, confidence}   (not saved)
POST   /diet/meals/   multipart {meal_type, eaten_at, description, items(json), photo?, source}
  → Meal
PATCH  /diet/meals/{id}/  /  DELETE /diet/meals/{id}/
  Meal = {id, eaten_at, local_date, meal_type, description, photo_url|null, items,
          kcal, carbs_g, protein_g, fat_g, source, ai_confidence}
GET    /diet/trend/?range=3m|6m|1y
  → { series: [{date, intake_kcal|null, target_kcal, weight_kg|null}],
      summary: {avg_balance_kcal|null, predicted_kg_per_week|null, actual_kg_per_week|null,
                logged_days_last_7} }
```

Errors: `{detail}` with proper status codes. Dates are always the athlete's local dates.

---

## 6. Milestones

- **R0 Scaffold** — copied backend boots under compose on new ports (8001/5174/5434/6381);
  new frontend shell with 4 tabs, theme tokens, auth. Done: login works, tabs render.
- **R1 Plans & Calendar** — models, materialisation, calendar endpoint, workout bar,
  detail sheets, Profile plan card. Done: accepting a plan fills the calendar.
- **R2 Profile metrics** — fitness/status calculators + charts, metric entries, memory.
- **R3 Chat with tools** — threads, tool loop, plan proposals, Guide/Review.
- **R4 Diet** — targets, fueling, meal estimate (photo/text), balance vs weight.
- **R5 Polish** — empty states, offline message, install prompt, evals for chat tools.
