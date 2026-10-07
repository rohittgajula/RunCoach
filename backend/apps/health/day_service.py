"""R11 §B glue: read one athlete-day (intraday arrays, sleep, runs, habit logs) into the
pure `analysis.day` input, and shape the Day / trends / summary bodies."""

from __future__ import annotations

import datetime as dt

from analysis import day as maths
from analysis import day_trends
from apps.activities.models import Activity
from apps.ingest.models import DailyMetrics, IntradayDay

from .common import zone_of

HISTORY_DAYS = 56
HABIT_LABELS = {"smoke": "Cigarette", "alcohol": "Drink", "sugar": "Sugar", "private": "Private"}


def _minute(value: dt.datetime | None, day: dt.date) -> tuple[int | None, int]:
    """Sleep times are stored as local wall-clock time in a UTC-aware field (see
    garmin_wellness._local_dt). Returns (minute, day offset vs `day`)."""
    if value is None:
        return None, 0
    naive = value.replace(tzinfo=None)
    return naive.hour * 60 + naive.minute, (naive.date() - day).days


def stats_summary(metrics: DailyMetrics | None) -> dict:
    """Garmin's daily totals from the stored user summary (get_stats)."""
    if metrics is None:
        return {}
    stats = (metrics.raw or {}).get("stats") or {}

    def num(key):
        value = stats.get(key)
        try:
            return int(round(float(value))) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {"total_steps": num("totalSteps") if num("totalSteps") is not None else metrics.steps,
            "step_goal": num("dailyStepGoal"),
            "sedentary_s": num("sedentarySeconds"), "active_s": num("activeSeconds"),
            "highly_active_s": num("highlyActiveSeconds"), "sleeping_s": num("sleepingSeconds"),
            "bb_charged": num("bodyBatteryChargedValue"),
            "bb_drained": num("bodyBatteryDrainedValue"),
            "bb_at_wake": num("bodyBatteryAtWakeTime"),
            "resting_hr": num("restingHeartRate") or metrics.resting_hr,
            "stress_avg": metrics.stress_avg}


def _runs(athlete, day: dt.date) -> list[dict]:
    zone = zone_of(athlete)
    out = []
    for a in Activity.objects.filter(athlete=athlete, local_date=day).order_by("started_at"):
        local = a.started_at.astimezone(zone)
        if local.date() != day:
            continue
        start = local.hour * 60 + local.minute
        end = start + max(1, round((a.total_elapsed_s or a.total_timer_s or 0) / 60))
        km = (a.total_distance_m or 0) / 1000
        sport = "Run" if "run" in (a.sport or "") else (a.sport or "Activity").replace("_", " ").title()
        label = f"{sport} · {km:.1f} km" if km >= 0.1 else sport
        out.append({"start": start, "end": min(end, maths.DAY_MIN), "activity_id": a.pk,
                    "label": label})
    return out


def _habits(athlete, day: dt.date) -> list[dict]:
    from apps.habits.models import HabitLog

    kinds = ["smoke", "alcohol", "sugar"] + (["private"] if athlete.private_habit_enabled else [])
    zone = zone_of(athlete)
    out = []
    for log in HabitLog.objects.filter(athlete=athlete, local_date=day, kind__in=kinds):
        local = log.at.astimezone(zone)
        label = HABIT_LABELS[log.kind]
        if log.quantity and log.quantity != 1:
            label = f"{label} ×{log.quantity:g}"
        out.append({"minute": local.hour * 60 + local.minute, "kind": log.kind, "label": label})
    return out


def day_input(athlete, day: dt.date, *, row: IntradayDay | None = None,
              history: bool = True) -> maths.DayInput:
    if row is None:
        row = IntradayDay.objects.filter(athlete=athlete, day=day).first()
    metrics = {m.metric_date: m for m in DailyMetrics.objects.filter(
        athlete=athlete, metric_date__in=[day, day + dt.timedelta(days=1)])}
    this, nxt = metrics.get(day), metrics.get(day + dt.timedelta(days=1))
    wake_min = night_start = bed_min = None
    if this is not None:
        m, off = _minute(this.sleep_end_local, day)
        wake_min = m if off == 0 else None
        m, off = _minute(this.sleep_start_local, day)
        night_start = m if off == 0 else None
    if nxt is not None:
        m, off = _minute(nxt.sleep_start_local, day)
        if m is not None and off in (0, 1):
            bed_min = m + off * maths.DAY_MIN
    next_bb = None
    if bed_min is not None and bed_min >= maths.DAY_MIN:
        next_bb = (IntradayDay.objects.filter(athlete=athlete, day=day + dt.timedelta(days=1))
                   .values_list("body_battery", flat=True).first())
    summary = stats_summary(this)
    steps = row.steps if row else []
    if row is not None:
        bucket_total = sum(int(r[1] or 0) for r in steps)
        if steps and (summary.get("total_steps") is None or bucket_total > summary["total_steps"]):
            summary["total_steps"] = bucket_total     # a later intraday refresh is newer
        summary["step_goal"] = summary.get("step_goal") or row.step_goal
        summary["resting_hr"] = summary.get("resting_hr") or row.resting_hr
    inp = maths.DayInput(
        date=day, is_today=day == athlete.local_today,
        hr=row.hr if row else [], stress=row.stress if row else [],
        body_battery=row.body_battery if row else [], steps=steps,
        wake_min=wake_min, bed_min=bed_min, night_start_min=night_start,
        next_body_battery=next_bb, summary=summary, runs=_runs(athlete, day),
        habits=_habits(athlete, day))
    if history:
        start = day - dt.timedelta(days=HISTORY_DAYS)
        intraday = {r["day"]: r for r in IntradayDay.objects.filter(
            athlete=athlete, day__gte=start, day__lt=day).values("day", "steps_total", "step_goal",
                                                                  "awake_hr_avg")}
        daily = {m.metric_date: m for m in DailyMetrics.objects.filter(
            athlete=athlete, metric_date__gte=start, metric_date__lt=day)}
        for d in sorted(set(intraday) | set(daily)):
            iv = intraday.get(d) or {}
            dm = daily.get(d)
            inp.step_history[d] = iv.get("steps_total") or (dm.steps if dm else None)
            goal = iv.get("step_goal") or (stats_summary(dm).get("step_goal") if dm else None)
            inp.goal_history[d] = goal
            inp.awake_hr_history[d] = iv.get("awake_hr_avg")
        inp.run_dates = set(Activity.objects.filter(
            athlete=athlete, sport__icontains="run", local_date__gte=start,
            local_date__lte=day).values_list("local_date", flat=True))
    return inp


def day_json(athlete, day: dt.date) -> dict:
    row = IntradayDay.objects.filter(athlete=athlete, day=day).first()
    body = maths.analyse(day_input(athlete, day, row=row))
    today = athlete.local_today
    firsts = [IntradayDay.objects.filter(athlete=athlete).order_by("day")
              .values_list("day", flat=True).first(),
              DailyMetrics.objects.filter(athlete=athlete).order_by("metric_date")
              .values_list("metric_date", flat=True).first()]
    firsts = [d for d in firsts if d]
    earliest = max(min(firsts), today - dt.timedelta(days=365)) if firsts else None
    prev_day = day - dt.timedelta(days=1)
    return {
        "date": day, "is_today": day == today, "available": row is not None,
        "complete": bool(row and row.complete),
        "fetched_at": row.fetched_at if row else None,
        **{"data_as_of": body.pop("data_as_of")},
        "prev_date": prev_day if earliest and prev_day >= earliest else None,
        "next_date": day + dt.timedelta(days=1) if day < today else None,
        **body,
    }


def summary_json(athlete) -> dict:
    today = athlete.local_today
    row = IntradayDay.objects.filter(athlete=athlete, day=today).first()
    inp = day_input(athlete, today, row=row)
    history = [inp.step_history[d] for d in sorted(inp.step_history)]
    goal, source = maths.choose_goal(inp.summary.get("step_goal"), maths.adaptive_goal(history))
    total = inp.summary.get("total_steps")
    last = [s[-1][0] for s in (inp.hr, inp.stress, inp.body_battery) if s]
    if inp.steps:
        last.append(inp.steps[-1][0] + maths.BUCKET_MIN)
    return {
        "date": today, "available": row is not None, "steps": total, "step_goal": goal,
        "goal_source": source,
        "pct": round(total / goal * 100) if total is not None and goal else None,
        "stress": inp.stress[-1][1] if inp.stress else None,
        "stress_at": maths.hhmm(inp.stress[-1][0]) if inp.stress else None,
        "body_battery": inp.body_battery[-1][1] if inp.body_battery else None,
        "body_battery_at": maths.hhmm(inp.body_battery[-1][0]) if inp.body_battery else None,
        "data_as_of": maths.hhmm(max(last)) if last else None,
        "fetched_at": row.fetched_at if row else None,
    }


# --- trends ---------------------------------------------------------------------------

DAY_KEYS = ("steps", "step_goal", "active_min", "sedentary_min", "stress_avg",
            "stress_high_min", "stressful_min", "awake_hr_avg", "bb_charged", "bb_drained",
            "bb_at_wake", "bb_at_bedtime")


def day_rows(athlete, start: dt.date, end: dt.date) -> list[dict]:
    intraday = {r.day: r for r in IntradayDay.objects.filter(
        athlete=athlete, day__gte=start, day__lte=end).defer("hr", "body_battery", "steps")}
    daily = {m.metric_date: m for m in DailyMetrics.objects.filter(
        athlete=athlete, metric_date__gte=start, metric_date__lte=end)
        .only("metric_date", "steps", "stress_avg")}
    rows = []
    for d in sorted(set(intraday) | set(daily)):
        r, m = intraday.get(d), daily.get(d)
        if r is None and (m is None or (m.steps is None and m.stress_avg is None)):
            continue
        row = {"date": d, **{k: None for k in DAY_KEYS}}
        if r is not None:
            row.update({k: getattr(r, k) for k in DAY_KEYS if k != "steps"})
            row["steps"] = r.steps_total
        if m is not None:
            row["steps"] = row["steps"] if row["steps"] is not None else m.steps
            row["stress_avg"] = row["stress_avg"] if row["stress_avg"] is not None else m.stress_avg
        rows.append(row)
    return rows


def _nights(athlete, start: dt.date, end: dt.date) -> dict:
    return {m.metric_date: {"sleep_score": m.sleep_score, "hrv": m.hrv_overnight_avg,
                            "sleep_h": round(m.sleep_seconds / 3600, 2) if m.sleep_seconds else None}
            for m in DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=start,
                                                 metric_date__lte=end)}


def _next_runs(athlete, start: dt.date, end: dt.date) -> dict:
    from .compare_views import series_for

    easy = series_for(athlete, "easy_hr", start, end)
    eff = series_for(athlete, "efficiency", start, end)
    return {d: {"easy_hr": easy.get(d), "efficiency": eff.get(d)} for d in set(easy) | set(eff)}


def trends_json(athlete, period) -> dict:
    from analysis.buckets import bucket

    from .period import as_period

    period = as_period(athlete, period)
    start, end = period.start, period.end
    days = day_rows(athlete, start, end)
    prev = day_rows(athlete, period.compare_start, period.compare_end)
    stress_by_day = dict(IntradayDay.objects.filter(athlete=athlete, day__gte=start, day__lte=end)
                         .values_list("day", "stress"))
    goal_days = {d["date"]: (d["steps"], d["step_goal"]) for d in days}
    history = [d["steps"] for d in days if d["steps"]]
    adaptive = maths.adaptive_goal(history)
    goal_days = {d: (s, g or adaptive) for d, (s, g) in goal_days.items()}
    return {
        **period.ranged(),
        "days": bucket(days, period.freq, {"steps": "sum", "*": "mean"}, digits=0),
        "averages": day_trends.averages(days),
        "previous": day_trends.averages(prev),
        "weeks": day_trends.weeks(days),
        "awake_hr_trend": day_trends.awake_hr_trend(days),
        "weekday_pattern": day_trends.weekday_pattern(days, stress_by_day),
        "goal_streak": maths.goal_streak(goal_days, end, allow_unmet_end=end == athlete.local_today),
        "day_night_run": day_trends.day_night_run(
            days, _nights(athlete, start, end + dt.timedelta(days=1)),
            _next_runs(athlete, start, end + dt.timedelta(days=2))),
    }
