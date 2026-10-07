# R9 — Insights sections, private habit, habit health report, progress dates + bullets, guides

Requested by Rohit 2026-10-07. Same rules: Python calculates, the model interprets; safety
only makes training easier; tenant isolation; health data leaves only as aggregates to the
AI. **No new bottom tab** — Rohit finds more bottom sections cluttered.

---

## A. Insights gets sections (frontend only)

- Insights page header keeps Settings; under it a sticky segmented switch:
  **Overview · Progress · Habits · Guides**. Routes `/insights` (overview),
  `/insights/progress`, `/insights/habits`, `/insights/guides` (deep-linkable, back button
  works, each section scrolls to top on switch). Bottom tab bar unchanged (5 tabs).
- Overview = today's existing cards **minus** HabitsSection; the ProgressCard on Overview
  becomes a one-row teaser ("Last 5 runs: pace 6 s/km faster · HR −3 bpm  ›") linking to
  the Progress section; a one-row Habits teaser (smoke-free streak / today's counts ›).
- Calendar today card keeps the quick-log row (🚬 🍺 🍫, plus 🌙 only if the private
  habit is enabled **and** `private_on_today`).

## B. Private habit

- `HabitLog.kind` gains `private` (count). UI label everywhere: **"Private"**, icon 🌙.
  The word for it never appears in the UI, API labels, AI prompts or chat.
- Athlete fields: `private_habit_enabled` (bool, default false), `private_on_today`
  (bool, default false), `private_goal` (`reduce|none`, default none).
- Settings → Habits: "Private habit" toggle with helper "Shown only as 🌙 Private. Never
  shown to the coach or in chat." + "Show on today card" toggle + goal.
- When disabled: `/habits/today/` and `/habits/summary/` omit `private` entirely; POST of
  kind `private` → 400. Existing logs stay until the user deletes them (Settings: "Delete
  private logs" button → `DELETE /habits/logs/?kind=private`, confirm in-page).
- **Excluded from AI**: not in the chat system prompt, not loggable through the chat tool,
  not in the AI habit summary input, not in morning check-in signals. Deterministic
  feedback only.
- In the Habits section its card is collapsed + blurred by default ("Tap to show"),
  remembered per device (localStorage).

## C. Habit health report ("has it improved or hurt me?")

Extend `GET /habits/summary/?range=4w|12w|6m` with `report` (pure `analysis/habits.py`,
new functions; existing fields unchanged):

```
report: {
  overall: {status: "improving"|"worsening"|"steady"|"not_enough_data", headline: str},
  garmin: [ {metric, label, unit, now, before, delta, better: bool|null} ],
      # range vs the same-length range before it: hrv, rhr, sleep_score, stress,
      # body_battery_high, respiration, easy_pace_hr (runs), efficiency (runs)
  habits: [ {
    habit: "smoke"|"alcohol"|"sugar"|"private",
    status: "improving"|"worsening"|"steady"|"not_enough_data",
    headline: str,                       # e.g. "Down 38% vs the previous 4 weeks"
    amount: {now_per_day, before_per_day, change_pct},
    findings: [ {tone: "good"|"bad"|"neutral", text: str, kind: str} ]
  } ]
}
```

Findings per habit, each only when its data threshold is met (else one neutral
"keep logging" finding saying what is missing):
1. **Amount trend** — per-day (smoke/sugar/private) or per-week (alcohol) now vs previous
   range. ±10 % = steady.
2. **Next-morning effect** — existing `impact` rows with `enough_data` (n ≥ 5 each),
   phrased "On mornings after …, your HRV averaged X ms lower (n=…)". tone bad/good.
3. **Dose** — alcohol 1–2 vs 3+ drinks when ≥ 3 nights each.
4. **Timing** — alcohol/sugar/private logged after 21:00 local vs earlier → sleep score
   and HRV next morning, ≥ 4 nights each.
5. **Weekly link** — Spearman ρ between weekly amount and weekly HRV / RHR / sleep
   score over the range (≥ 6 weeks with data); report when |ρ| ≥ 0.4: "Weeks with more
   cigarettes tended to have lower HRV (ρ=−0.55, 9 weeks)". Never causal wording.
6. **Since quit** (smoke with quit date ≥ 7 days ago): 14 days before quit vs days since
   quit for HRV, RHR, sleep score, easy-pace HR (≥ 5 days each side).
7. **Next-day run** — easy-pace HR / efficiency on runs the day after exposure vs clean
   (≥ 3 runs each).

`status` per habit: amount down ≥10 % and no new bad findings → improving; up ≥10 % → worsening;
else steady; too little logging → not_enough_data. `overall` combines: improving if
majority of logged habits improving and Garmin HRV/RHR not worse.

AI summary (`POST ?refresh=1`) gets `report` without `private` entries.

UI Habits section: range switch (4w · 12w · 6m) → **Health report** card (overall
headline + status pill, Garmin "then → now" grid with green/red arrows) → per-habit
cards (headline, status pill, amount chart, findings as coloured bullets) → Since quit
card → Impact detail → AI summary → log history list (edit/delete).

## D. Progress: custom dates + bullet points

- `GET /progress/?start=YYYY-MM-DD&end=YYYY-MM-DD[&compare_start=&compare_end=]` —
  current = runs in [start, end]; previous = the same-length period just before (or the
  given compare range). `window` and dates are mutually exclusive (400 if both; max
  range 730 days; start ≤ end). Response gains
  `period: {mode: "window"|"dates", start, end, compare_start, compare_end, runs_current,
  runs_previous}` in both modes.
- New `highlights: [{tone: "good"|"bad"|"neutral", text}]` (pure `analysis/progress.py`),
  max 6, good first: metric changes with readable values ("Run pace 7:12 → 6:58 /km —
  14 s faster"), new bests in the period, distance-bucket like-for-like change, consistency
  (runs/week now vs before). Present even with 1 run (neutral "Only one run in this
  period").
- `POST /progress/review/` accepts the same date params; cache key includes them.
- UI: segmented **1 · 5 · 10 · 20 · Dates**; Dates opens two date inputs (from/to,
  default last 30 days) + optional "compare with" range; "Summary" bullet list (coloured
  dots) directly under the switch, before the table/chart.

## E. Guides (visual action guides)

- `GET /guides/` → `{for_you: [{key, reason, priority}], context: {...}}` from pure
  `analysis/guides.py` rules over recent data (last 28 days):
  - cadence avg < 160 spm → `form` ("Your cadence averages 152 spm")
  - HR drift > 5 % on ≥ 2 runs → `breathing`, `fueling`
  - smoke goal quit/reduce or smoking logged → `breathing` (lung recovery)
  - run fraction < 0.85 (run/walk) → `strength`, `breathing`
  - hot forecast (feels-like ≥ 28 °C) or upcoming run ≥ 60 min this week → `fueling`
  - always available: `warmup`. Sorted by priority, deduped, reasons merged.
- Frontend-static content (no AI), each guide a full sheet with **SVG illustrations /
  CSS animations**, theme-aware, works at 400 px:
  1. **Form — how to land**: animated side-view runner (good: foot lands under hips,
     midfoot, slight forward lean; vs overstride: heel far ahead) toggle; 5 cues; a
     **cadence metronome** (WebAudio clicks, bpm default = athlete cadence + 5 %, ±).
  2. **Breathing**: rhythm patterns by effort (easy 3:3 / nasal, steady 2:2, hard 2:1)
     with animated step dots; **breathing pacer** (expanding circle; box 4-4-4-4,
     diaphragmatic 4-6, pursed-lip) with a 3/5-min timer; lung-recovery note when smoking.
  3. **Strength & drills**: 8 exercise cards with simple SVG figures (calf raise, glute
     bridge, split squat, plank, side plank, clamshell, A-skip, hip-flexor stretch), sets ×
     reps, "2× per week, ~20 min", a "today's circuit" with a simple step timer.
  4. **Fueling**: timeline graphic (3 h before · 60 min · during · within 30 min after)
     filled from Diet targets + today's weather hydration; plate graphic per day type
     (rest / easy / hard-long) with carb/protein/veg proportions.
  5. **Warm-up & cool-down**: sequence with durations and a step timer.
- Guides section: "For you" row (cards with reason) then all guides grid. Progress focus
  items and Insights focus items that match a guide get an "Open guide ›" link
  (`/insights/guides?g=form`).

## F. Not changed
Deploy, auth, Garmin, plan logic. Account deletion already covers HabitLog.
