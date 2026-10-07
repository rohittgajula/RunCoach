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

KINDS = ("smoke", "alcohol", "sugar")
RANGES = {"4w": 28, "12w": 84, "6m": 182}
DEFAULT_RANGE = "4w"
EASY_PACE_SLACK_S = 30


def log_json(log: HabitLog) -> dict:
    return {"id": log.pk, "kind": log.kind, "quantity": log.quantity, "at": log.at,
            "local_date": log.local_date, "note": log.note, "created_at": log.created_at}


def counts_on(athlete, day: dt.date) -> dict:
    rows = (HabitLog.objects.filter(athlete=athlete, local_date=day)
            .values("kind").annotate(total=Sum("quantity")))
    totals = {r["kind"]: round(r["total"] or 0, 2) for r in rows}
    return {k: totals.get(k, 0) for k in KINDS}


def today_payload(athlete) -> dict:
    today = athlete.local_today
    last_at = {}
    for kind in KINDS:
        last = (HabitLog.objects.filter(athlete=athlete, kind=kind)
                .order_by("-at").values_list("at", flat=True).first())
        last_at[kind] = last
    return {"date": today, "counts": counts_on(athlete, today), "last_at": last_at}


def _totals(athlete, kind: str, since: dt.date | None = None) -> dict[dt.date, float]:
    qs = HabitLog.objects.filter(athlete=athlete, kind=kind)
    if since:
        qs = qs.filter(local_date__gte=since)
    return maths.daily_totals(list(qs.values_list("local_date", "quantity")))


def _mornings(athlete, start: dt.date, end: dt.date) -> dict[dt.date, dict]:
    rows = DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=start,
                                       metric_date__lte=end)
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


def _smoke(athlete, totals, start, today) -> dict:
    tracking = _tracking_start(totals, athlete.smoke_quit_date)
    days = _window(start, today, tracking)
    points = maths.series(totals, start, today)
    tracked = [p for p in points if days and p["date"] >= days[0].isoformat()]
    total = round(sum(totals.get(d, 0) for d in days), 1)
    denominator = avg_days(start, today, tracking)
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


def summary_payload(athlete, range_key: str) -> dict:
    from .ai import summary_state

    today = athlete.local_today
    start = today - dt.timedelta(days=RANGES[range_key] - 1)
    totals = {k: _totals(athlete, k) for k in KINDS}
    mornings = _mornings(athlete, start, today + dt.timedelta(days=1))
    runs = _runs(athlete, start, today)
    impact = []
    for kind in KINDS:
        extra = athlete.smoke_quit_date if kind == "smoke" else None
        days = [d for d in _window(start, today, _tracking_start(totals[kind], extra))
                if d < today]
        if days:
            impact += maths.impact(kind, totals[kind], days, mornings, runs)
    return {
        "range": range_key, "today": today,
        "smoke": _smoke(athlete, totals["smoke"], start, today),
        "alcohol": _simple(totals["alcohol"], start, today, weekly=True),
        "sugar": _simple(totals["sugar"], start, today, weekly=False),
        "impact": impact,
        "weekly": maths.weekly(start, today, totals, mornings, runs),
        "goals": {"smoke": athlete.smoke_goal, "alcohol": athlete.alcohol_goal,
                  "sugar": athlete.sugar_goal},
        "summary": summary_state(athlete, today),
    }


def smoke_streak(athlete) -> dict:
    totals = _totals(athlete, "smoke")
    return maths.streak(totals, athlete.local_today,
                        _tracking_start(totals, athlete.smoke_quit_date))


def chat_context(athlete) -> dict | None:
    """Aggregates for the chat system prompt: today's / yesterday's counts, goals and
    the smoke-free streak. None when the athlete tracks nothing."""
    today = athlete.local_today
    tracks = (HabitLog.objects.filter(athlete=athlete).exists()
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
