"""Habits (R8 §B): logging, today's counts and the /habits/summary/ payload.

Every number is computed here or in analysis/habits.py. The AI summary is written from
the aggregate payload only (counts, averages, differences) — never from log rows.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from django.db.models import Sum

from analysis import habits as maths
from apps.activities.models import Activity
from apps.ingest.models import DailyMetrics

from .models import HabitLog

KINDS = ("smoke", "alcohol", "sugar")          # the habits the AI may ever see
PRIVATE = "private"                             # R9 §B: never sent to the AI
ALL_KINDS = (*KINDS, PRIVATE)
CAFFEINE = "caffeine"                           # R13 §9: its own report, not the summary
LOGGABLE_KINDS = (*ALL_KINDS, CAFFEINE)
CAFFEINE_TYPES = ("coffee", "tea", "energy", "other")
RANGES = {"4w": 28, "12w": 84, "6m": 182}
PREVIOUS_LABELS = {"4w": "the previous 4 weeks", "12w": "the previous 12 weeks",
                   "6m": "the previous 6 months"}
MAX_HISTORY_DAYS = 800
DEFAULT_RANGE = "4w"
EASY_PACE_SLACK_S = 30


def log_json(log: HabitLog) -> dict:
    return {"id": log.pk, "kind": log.kind, "quantity": log.quantity, "at": log.at,
            "local_date": log.local_date, "note": log.note,
            "subtype": (log.subtype or None) if log.kind == CAFFEINE else None,
            "created_at": log.created_at}


def kinds_for(athlete) -> tuple[str, ...]:
    """The habits shown to this athlete: the private one only when enabled."""
    return ALL_KINDS if athlete.private_habit_enabled else KINDS


def counts_on(athlete, day: dt.date, include_private: bool = False) -> dict:
    """Counts for one day. `include_private` is for the athlete's own screens only —
    the default (used by chat) never includes the private habit."""
    kinds = kinds_for(athlete) if include_private else KINDS
    rows = (HabitLog.objects.filter(athlete=athlete, local_date=day, kind__in=kinds)
            .values("kind").annotate(total=Sum("quantity")))
    totals = {r["kind"]: round(r["total"] or 0, 2) for r in rows}
    return {k: totals.get(k, 0) for k in kinds}


def today_payload(athlete) -> dict:
    today = athlete.local_today
    last_at = {}
    for kind in kinds_for(athlete):
        last = (HabitLog.objects.filter(athlete=athlete, kind=kind)
                .order_by("-at").values_list("at", flat=True).first())
        last_at[kind] = last
    caffeine = HabitLog.objects.filter(athlete=athlete, kind=CAFFEINE)
    return {"date": today, "counts": counts_on(athlete, today, include_private=True),
            "last_at": last_at,
            # R13 §9: kept out of `counts` so existing habit tiles are unchanged.
            "caffeine": {
                "count": round(caffeine.filter(local_date=today)
                               .aggregate(total=Sum("quantity"))["total"] or 0, 2),
                "last_at": caffeine.order_by("-at").values_list("at", flat=True).first(),
                "on_today": athlete.caffeine_on_today}}


def _totals(athlete, kind: str, since: dt.date | None = None) -> dict[dt.date, float]:
    qs = HabitLog.objects.filter(athlete=athlete, kind=kind)
    if since:
        qs = qs.filter(local_date__gte=since)
    return maths.daily_totals(list(qs.values_list("local_date", "quantity")))


def _mornings(athlete, start: dt.date, end: dt.date) -> dict[dt.date, dict]:
    from apps.health.data_review import excluded_days

    # R17: days the athlete explicitly excluded (e.g. while ill) are left out.
    rows = DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=start,
                                       metric_date__lte=end) \
        .exclude(metric_date__in=excluded_days(athlete))
    return {r.metric_date: {"hrv": r.hrv_overnight_avg, "rhr": r.resting_hr,
                            "sleep_score": r.sleep_score,
                            "body_battery": r.body_battery_high, "stress": r.stress_avg,
                            "sleep_respiration": r.respiration_sleep_avg} for r in rows}


def _runs(athlete, start: dt.date, end: dt.date) -> dict[dt.date, dict]:
    """Per day: mean HR / pace on easy runs, efficiency (m/min per bpm), HR drift."""
    easy_limit = athlete.easy_pace_min - EASY_PACE_SLACK_S
    by_day: dict[dt.date, list] = {}
    for a in (Activity.objects.filter(athlete=athlete, sport__icontains="run",
                                      local_date__gte=start, local_date__lte=end)
              .exclude(quality__decision="exclude")
              .select_related("metrics")):
        m = getattr(a, "metrics", None)
        if m is None or not m.run_pace_s_per_km or not m.avg_run_hr:
            continue
        by_day.setdefault(a.local_date, []).append(m)
    out = {}
    for day, ms in by_day.items():
        easy = [m for m in ms if m.run_pace_s_per_km >= easy_limit]
        drift = [m.hr_drift_percent for m in ms if m.hr_drift_percent is not None]
        out[day] = {
            "easy_hr": maths_mean([m.avg_run_hr for m in easy]),
            "easy_pace": maths_mean([m.run_pace_s_per_km for m in easy]),
            "efficiency": maths_mean([(60000 / m.run_pace_s_per_km) / m.avg_run_hr
                                      for m in ms], 3),
            "hr_drift": maths_mean(drift),
        }
    return out


def maths_mean(values, digits: int = 1):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), digits) if values else None


def quit_moment(athlete) -> dt.datetime | None:
    if not athlete.smoke_quit_date:
        return None
    try:
        zone = ZoneInfo(athlete.timezone or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    return dt.datetime.combine(athlete.smoke_quit_date, dt.time(0, 0), tzinfo=zone)


def _tracking_start(totals: dict, extra: dt.date | None = None) -> dt.date | None:
    starts = [d for d in (min(totals) if totals else None, extra) if d is not None]
    return min(starts) if starts else None


MIN_AVG_DAYS = 7


def avg_days(start: dt.date, today: dt.date, first_ever: dt.date | None) -> int:
    """Denominator for averages: the whole range window, or the time since the first
    ever log (at least a week) when that is shorter — never the days that have data."""
    window = (today - start).days + 1
    if first_ever is None:
        return window
    return min(window, max((today - first_ever).days + 1, MIN_AVG_DAYS))


def _window(start: dt.date, today: dt.date, tracking: dt.date | None) -> list[dt.date]:
    first = max(start, tracking) if tracking else None
    if first is None or first > today:
        return []
    return [first + dt.timedelta(days=i) for i in range((today - first).days + 1)]


def _smoke(athlete, totals, start, end) -> dict:
    today = athlete.local_today
    tracking = _tracking_start(totals, athlete.smoke_quit_date)
    days = _window(start, end, tracking)
    points = maths.series(totals, start, end)
    tracked = [p for p in points if days and p["date"] >= days[0].isoformat()]
    total = round(sum(totals.get(d, 0) for d in days), 1)
    denominator = avg_days(start, end, tracking)
    quit_at = quit_moment(athlete)
    smoked_since = 0.0
    if quit_at is not None:
        after = HabitLog.objects.filter(athlete=athlete, kind="smoke", at__gte=quit_at)
        smoked_since = sum(after.values_list("quantity", flat=True))
        last = after.order_by("-at").values_list("at", flat=True).first()
        quit_at = max(quit_at, last) if last else quit_at
    return {
        "series": points, "total": total,
        "per_day_avg": round(total / denominator, 2) if days else None,
        "trend_per_week": maths.trend_per_week(tracked),
        "streak": maths.streak(totals, today, tracking),
        "since_quit": maths.since_quit(athlete.smoke_quit_date, today,
                                       athlete.smoke_baseline_per_day,
                                       athlete.cigarette_price, smoked_since),
        "milestones": maths.milestones(quit_at, athlete.local_now),
    }


def _simple(totals, start, today, weekly: bool) -> dict:
    first = _tracking_start(totals)
    days = _window(start, today, first)
    total = round(sum(totals.get(d, 0) for d in days), 1)
    denominator = avg_days(start, today, first)
    out = {"series": maths.series(totals, start, today), "total": total}
    if weekly:
        out["per_week_avg"] = round(total / (denominator / 7), 1) if days else None
        out["drink_days"] = sum(1 for d in days if totals.get(d, 0) > 0)
    else:
        out["per_day_avg"] = round(total / denominator, 2) if days else None
    return out


def _late_days(athlete, kind: str, start: dt.date, end: dt.date) -> set[dt.date]:
    """Days with a log of `kind` at or after 21:00 local time."""
    try:
        zone = ZoneInfo(athlete.timezone or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    rows = HabitLog.objects.filter(athlete=athlete, kind=kind, local_date__gte=start,
                                   local_date__lte=end).values_list("local_date", "at")
    return {day for day, at in rows if at.astimezone(zone).hour >= maths.LATE_HOUR}


def _tracked(athlete, kind: str, totals: dict) -> bool:
    goal = {"smoke": athlete.smoke_goal, "alcohol": athlete.alcohol_goal,
            "sugar": athlete.sugar_goal, PRIVATE: athlete.private_goal}[kind]
    return bool(totals) or goal not in ("none", "") or (
        kind == "smoke" and athlete.smoke_quit_date is not None)


def _goals(athlete) -> dict:
    goals = {"smoke": athlete.smoke_goal, "alcohol": athlete.alcohol_goal,
             "sugar": athlete.sugar_goal}
    if athlete.private_habit_enabled:
        goals[PRIVATE] = athlete.private_goal
    return goals


def previous_label(period) -> str:
    if period.range_key in PREVIOUS_LABELS:
        return PREVIOUS_LABELS[period.range_key]
    if period.range_key == "7d":
        return "the previous 7 days"
    return f"the previous {period.days} days"


def summary_payload(athlete, range_key, with_report: bool = True) -> dict:
    """`range_key`: a preset key or an R12 Period (custom start/end, freq)."""
    from analysis.buckets import bucket

    from apps.health.period import LEGACY, as_period

    from .ai import summary_state

    period = as_period(athlete, range_key, extra=LEGACY)
    today = athlete.local_today
    start, end = period.start, period.end
    prev_start, prev_end = period.compare_start, period.compare_end
    kinds = kinds_for(athlete)
    totals = {k: _totals(athlete, k) for k in kinds}
    history_start = prev_start
    if athlete.smoke_quit_date:
        history_start = min(history_start, athlete.smoke_quit_date
                            - dt.timedelta(days=maths.QUIT_BEFORE_DAYS))
    history_start = max(history_start, today - dt.timedelta(days=MAX_HISTORY_DAYS))
    mornings = _mornings(athlete, history_start, today + dt.timedelta(days=1))
    runs = _runs(athlete, history_start, today)
    window_end = end
    impact, impact_prev, tracking = [], [], {}
    for kind in kinds:
        extra = athlete.smoke_quit_date if kind == "smoke" else None
        tracking[kind] = _tracking_start(totals[kind], extra)
        days = [d for d in _window(start, window_end, tracking[kind]) if d < today]
        if days:
            impact += maths.impact(kind, totals[kind], days, mornings, runs)
        prev_days = [d for d in _window(prev_start, prev_end, tracking[kind])]
        if with_report and prev_days:
            impact_prev += maths.impact(kind, totals[kind], prev_days, mornings, runs)
    payload = {
        **period.ranged(), "today": today,
        "smoke": _smoke(athlete, totals["smoke"], start, window_end),
        "alcohol": _simple(totals["alcohol"], start, window_end, weekly=True),
        "sugar": _simple(totals["sugar"], start, window_end, weekly=False),
        "impact": impact,
        "weekly": maths.weekly(start, window_end, totals, mornings, runs),
        "goals": _goals(athlete),
        "summary": summary_state(athlete, today),
    }
    if PRIVATE in kinds:
        payload[PRIVATE] = _simple(totals[PRIVATE], start, window_end, weekly=False)
    for kind in ("smoke", "alcohol", "sugar", PRIVATE):
        if kind in payload:
            payload[kind]["series"] = bucket(payload[kind]["series"], period.freq, "sum")
    if with_report:
        label = previous_label(period)
        habits = [maths.habit_report(
            kind, totals=totals[kind], start=start, end=window_end, prev_start=prev_start,
            prev_end=prev_end, tracking=tracking[kind], impact_rows=impact,
            prev_impact_rows=impact_prev, mornings=mornings, runs=runs,
            late_days=(_late_days(athlete, kind, start, window_end)
                       if kind in maths.TIMING_HABITS else None),
            quit_date=athlete.smoke_quit_date if kind == "smoke" else None,
            previous_label=label) for kind in kinds if _tracked(athlete, kind, totals[kind])]
        garmin = maths.garmin_compare(mornings, runs, start, window_end, prev_start, prev_end)
        payload["report"] = maths.report(habits, garmin, label)
    return payload


def smoke_streak(athlete) -> dict:
    totals = _totals(athlete, "smoke")
    return maths.streak(totals, athlete.local_today,
                        _tracking_start(totals, athlete.smoke_quit_date))


def chat_context(athlete) -> dict | None:
    """Aggregates for the chat system prompt: today's / yesterday's counts, goals and
    the smoke-free streak. None when the athlete tracks nothing."""
    today = athlete.local_today
    tracks = (HabitLog.objects.filter(athlete=athlete, kind__in=KINDS).exists()
              or "quit" == athlete.smoke_goal or athlete.smoke_goal == "reduce"
              or athlete.alcohol_goal == "reduce" or athlete.sugar_goal == "reduce")
    if not tracks:
        return None
    since = maths.since_quit(athlete.smoke_quit_date, today, None, None, 0)
    return {"today": counts_on(athlete, today),
            "yesterday": counts_on(athlete, today - dt.timedelta(days=1)),
            "goals": {"smoke": athlete.smoke_goal, "alcohol": athlete.alcohol_goal,
                      "sugar": athlete.sugar_goal},
            "smoke_free_streak_days": smoke_streak(athlete)["current_days"],
            "days_since_quit": since["days"] if since else None}
