# R12 — Custom ranges + frequency in Health, alarms + watch alarm check

Requested by Rohit 2026-10-07.

## A. Ranges and frequency everywhere in Health
- Presets: **7d · 4w · 3m · 6m · 1y · Custom** (custom = from/to date picker, max 2 years,
  default last 30 days). One shared range control in the Health header; the choice
  persists per section in the URL (`?range=4w` or `?start=YYYY-MM-DD&end=YYYY-MM-DD`)
  and in localStorage.
- **Frequency** (`?freq=day|week|month`, default: day for ≤ 3 months, week for ≤ 1 year,
  month beyond): charts and trend tables aggregate by that bucket (mean for rates like
  HRV/RHR/stress/sleep score, sum for steps/km/drinks, last for VO2max/weight-like
  levels). Comparisons ("vs previous") always use the same-length period before.
- Backend: every Health endpoint that takes `range` (insights, fitness, sleep, form,
  body, day/trends, compare, habits summary, training-status history) also accepts
  `start`/`end` and `freq`; one shared parser/validator (400 with clear message; range
  xor dates; start ≤ end; ≤ 730 days); responses include
  `period: {start, end, compare_start, compare_end, freq}`. Pure bucketing helper in
  `analysis/` with tests. Keep old `range` values working.

## B. Alarms
Web apps cannot set the phone's alarm clock or write alarms to a Garmin watch through
any supported API, so:
1. **Wake planner** (Sleep section + Today evening card): suggested wake time from the
   next run time / plan + sleep need; suggested bedtime = wake − (sleep need + 15 min).
   User can save "My alarm" (time + days) in RunCoach.
2. **Set on phone**: on Android a "Set alarm on phone" button opens the Clock app with
   the time prefilled via an Android intent URL
   (`intent:#Intent;action=android.intent.action.SET_ALARM;i.android.intent.extra.alarm.HOUR=H;i.android.intent.extra.alarm.MINUTES=M;S.android.intent.extra.alarm.MESSAGE=RunCoach;end`);
   on iOS show the time + "open Clock" guidance. Fallback for all: a push reminder at
   the alarm time (R10 web push) — labelled as a notification, not a real alarm.
3. **Bedtime reminder**: push at suggested bedtime − 30 min (off by default).
4. **Watch alarm check** (read-only): read the alarms configured on the user's Garmin
   device (garminconnect `get_device_alarms` or the device settings call if present —
   verify in the 0.3.10 source) once per day with the slow fetch; show them in Sleep /
   Me ("Watch alarms: 06:00 Mon–Fri") and flag mismatches with the plan ("Your run is at
   6:30 but your watch alarm is 07:00" / "No alarm set for tomorrow's run"). Never
   write device settings. If the call isn't available, hide the card.
