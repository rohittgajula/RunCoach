"""Building a plan and today's session for a real athlete."""

from __future__ import annotations

import datetime as dt

from apps.activities.models import Activity
from apps.athletes.models import Athlete
from apps.ingest.models import DailyMetrics

from planning.baseline import HISTORY_WEEKS, HistoryBaseline, RunPoint, from_history
from planning.generator import Baseline, Plan, PlanConfig, Session, generate_plan
from planning.readiness import Adjustment, WellnessSnapshot, apply, assess

from .services import mode_for, races_for



def config_from_settings() -> PlanConfig:
    from django.conf import settings

    training = settings.TRAINING
    return PlanConfig(
        max_weekly_increase_pct=training["MAX_WEEKLY_INCREASE_PCT"],
        cutback_every_n_weeks=training["CUTBACK_EVERY_N_WEEKS"],
        cutback_factor=training["CUTBACK_FACTOR"],
        max_hard_sessions_per_week=training["MAX_HARD_SESSIONS_PER_WEEK"],
        max_long_run_pct_of_week=training["MAX_LONG_RUN_PCT_OF_WEEK"],
    )


def run_points(athlete: Athlete, since: dt.date | None = None) -> list[RunPoint]:
    """Segmented runs that contain actual running, oldest first."""
    queryset = Activity.objects.filter(athlete=athlete, sport="running")
    if since is not None:
        queryset = queryset.filter(local_date__gte=since)
    points = []
    for activity in queryset.select_related("metrics").order_by("local_date"):
        metrics = getattr(activity, "metrics", None)
        if metrics is None or metrics.run_block_count <= 0:
            continue
        points.append(RunPoint(
            date=activity.local_date, run_distance_m=metrics.run_distance_m,
            longest_run_s=metrics.longest_run_s,
            run_pace_s_per_km=metrics.run_pace_s_per_km,
            walk_pace_s_per_km=metrics.walk_pace_s_per_km,
        ))
    return points


def history_baseline(athlete: Athlete) -> HistoryBaseline:
    """The most recent block of running in the last 16 weeks, detrained for the gap."""
    today = athlete.local_today
    since = today - dt.timedelta(weeks=HISTORY_WEEKS)
    return from_history(run_points(athlete, since), today)


def baseline_for(athlete: Athlete) -> Baseline:
    """From segmented running history, never from a questionnaire.

    The baseline is the BEST week of the most recent block of running, not a mean:
    dividing a total by four punishes someone who only started three weeks ago. A gap
    since that block scales it down (see planning/baseline.py) — but a six-week break
    no longer erases the history, which is what made August's runs invisible.

    With no running in the last 16 weeks, longest_run_s is 0 and the caller treats the
    athlete as a beginner.
    """
    history = history_baseline(athlete)
    return Baseline(
        run_km_per_week=history.run_km_per_week,
        longest_run_s=history.longest_run_s,
        run_pace_s_per_km=history.run_pace_s_per_km or 480.0,
        walk_pace_s_per_km=history.walk_pace_s_per_km or 700.0,
        available_days=athlete.available_days or {},
        long_run_day=athlete.long_run_day,
    )


def plan_for(athlete: Athlete) -> Plan | None:
    """None when there is no target race to build towards."""
    target = next((r for r in races_for(athlete) if r.is_target), None)
    if target is None:
        upcoming = sorted(
            (r for r in races_for(athlete) if r.date >= athlete.local_today),
            key=lambda r: r.date,
        )
        target = upcoming[0] if upcoming else None
    if target is None:
        return None

    return generate_plan(
        plan_start=athlete.local_today,
        race_date=target.date,
        race_km=target.distance_km,
        baseline=baseline_for(athlete),
        config=config_from_settings(),
    )


def snapshot_for(athlete: Athlete, day: dt.date | None = None) -> WellnessSnapshot:
    day = day or athlete.local_today
    rows = list(
        DailyMetrics.objects.filter(athlete=athlete, metric_date__lte=day)
        .order_by("-metric_date")[:29]
    )
    if not rows:
        # No wellness data does NOT mean no signals — a pain report still counts.
        from apps.journal.services import flags_for

        return WellnessSnapshot(**flags_for(athlete, day), **_checkin_extras(athlete, day))

    today = rows[0] if rows[0].metric_date == day else None
    history = [r.hrv_overnight_avg for r in rows[1:] if r.hrv_overnight_avg]
    resting = [r.resting_hr for r in rows[1:] if r.resting_hr]

    # Resting HR and body battery are daytime figures: in the morning today's row is
    # often still empty while yesterday's is complete. One day old is still "current";
    # older is not. Sleep and HRV are deliberately NOT carried over — a night without
    # the watch is missing data, and last week's sleep says nothing about last night.
    yesterday = next((r for r in rows if r.metric_date == day - dt.timedelta(days=1)), None)

    def recent(field):
        for row in (today, yesterday):
            value = getattr(row, field, None) if row else None
            if value:
                return value
        return None

    # Subjective flags come from what the athlete actually said, and they outrank
    # every sensor reading below: excellent readiness does not overrule a pain report.
    from apps.journal.services import flags_for

    flags = flags_for(athlete, day)

    return WellnessSnapshot(
        readiness=today.training_readiness if today else None,
        sleep_hours=(today.sleep_seconds / 3600) if today and today.sleep_seconds else None,
        hrv=today.hrv_overnight_avg if today else None,
        hrv_baseline=history,
        resting_hr=recent("resting_hr"),
        resting_hr_baseline=resting,
        pain_reported=flags["pain_reported"],
        illness_reported=flags["illness_reported"],
        # Garmin's band moves slowly; the newest stored edge stands for today.
        hrv_baseline_low=next((r.hrv_baseline_low for r in rows if r.hrv_baseline_low), None),
        body_battery_high=recent("body_battery_high"),
        **_checkin_extras(athlete, day),
    )


def _checkin_extras(athlete: Athlete, day: dt.date) -> dict:
    """R7: ACWR of the custom load and yesterday's post-run RPE."""
    from apps.athletes.profile_views import daily_loads
    from apps.journal.models import JournalEntry

    loads = daily_loads(athlete)
    acute = sum(loads.get(day - dt.timedelta(days=i), 0.0) for i in range(7)) / 7
    chronic = sum(loads.get(day - dt.timedelta(days=i), 0.0) for i in range(28)) / 28
    rpes = [r for r in JournalEntry.objects.filter(
        athlete=athlete, applies_to_date=day - dt.timedelta(days=1), rpe__isnull=False,
    ).values_list("rpe", flat=True)]
    # Under three weeks of history the chronic side is not a baseline yet: a first
    # week of running always "spikes". Missing, not a warning.
    enough = bool(loads) and min(loads) <= day - dt.timedelta(days=21)
    return {
        "acwr": round(acute / chronic, 2) if chronic > 0 and enough else None,
        "last_rpe": max(rpes) if rpes else None,
        **_r8_extras(athlete, day),
    }


def _r8_extras(athlete: Athlete, day: dt.date) -> dict:
    """R8: drinks logged yesterday, and today's heat / air (today only; no weather = no
    signal)."""
    from django.db.models import Sum

    from apps.habits.models import HabitLog

    drinks = HabitLog.objects.filter(
        athlete=athlete, kind="alcohol", local_date=day - dt.timedelta(days=1),
    ).aggregate(total=Sum("quantity"))["total"]
    extras = {"drinks_yesterday": drinks}
    if day == athlete.local_today:
        from apps.ingest.weather_services import checkin_weather

        wx = checkin_weather(athlete)
        extras.update(heat_feels_like=wx.get("feels_like"), heat_dew_point=wx.get("dew_point"),
                      heat_hot=bool(wx.get("hot")), aqi=wx.get("aqi"))
    return extras


def session_on(athlete: Athlete, day: dt.date) -> Session | None:
    """The planned session for one date, before any readiness adjustment."""
    plan = plan_for(athlete)
    if plan is None:
        return None
    return next(
        (s for week in plan.weeks for s in week.sessions
         if s.date == day and not s.optional),
        None,
    )


def next_training_session(
    athlete: Athlete, after: dt.date, limit_days: int = 14
) -> Session | None:
    """The next real session strictly after `after`.

    Optional walks are skipped: easing a session that was never owed says nothing.
    """
    plan = plan_for(athlete)
    if plan is None:
        return None

    candidates = sorted(
        (s for week in plan.weeks for s in week.sessions
         if not s.optional and after < s.date <= after + dt.timedelta(days=limit_days)),
        key=lambda s: s.date,
    )
    return candidates[0] if candidates else None


def has_trained_on(athlete: Athlete, day: dt.date) -> bool:
    return Activity.objects.filter(athlete=athlete, local_date=day).exists()


def today_session(athlete: Athlete) -> tuple[Session | None, Adjustment | None, str]:
    """Today's prescription, after the readiness rules have had their say.

    Returns (session, adjustment, mode). The session is None on days the mode
    prescribes directly — recovery, maintenance, off_season — because the week table
    has no row that is right for those.
    """
    mode = mode_for(athlete)
    if mode.mode != "build":
        return None, None, mode.mode

    plan = plan_for(athlete)
    if plan is None:
        return None, None, mode.mode

    today = athlete.local_today
    planned = next(
        (s for week in plan.weeks for s in week.sessions if s.date == today), None
    )
    if planned is None:
        return None, None, mode.mode

    adjustment = assess(snapshot_for(athlete))
    return apply(planned, adjustment), adjustment, mode.mode
