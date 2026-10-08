"""R10 §C13 achievements and streaks. analysis/achievements.py decides what is earned
and when; this stores each one once (idempotent) and serves the badge grid."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import achievements as maths
from apps.activities.models import Activity
from apps.ingest.models import DailyMetrics

from .models import Achievement

RECENT = 10
# Reached longer ago than this when first stored (history, a first sync): stored as
# already seen, so the first visit is not a flood of "new badge" toasts.
QUIET_AFTER_DAYS = 7


def _smoke(athlete):
    from analysis import habits as habit_maths
    from apps.habits.models import HabitLog

    logs = list(HabitLog.objects.filter(athlete=athlete, kind="smoke")
                .values_list("local_date", "quantity"))
    tracked = logs or athlete.smoke_quit_date or athlete.smoke_goal in ("quit", "reduce")
    if not tracked:
        return None
    totals = habit_maths.daily_totals(logs)
    starts = [d for d in (min(totals) if totals else None, athlete.smoke_quit_date) if d]
    return maths.smoke_free(totals, min(starts) if starts else None, athlete.local_today)


def _pr_events(athlete) -> list[tuple[str, str, object]]:
    """(key, label, date) for every personal record we know of, Garmin's and ours."""
    from .garmin_views import records_list

    out = []
    for r in records_list(athlete):
        if r["date"] is None:
            continue
        key = f"pr:{r['source']}:{r['key']}:{r['date'].isoformat()}"
        out.append((key, f"New PR — {r['label']}: {r['display']}", r["date"]))
    return out


def evaluate(athlete) -> list[dict]:
    """The badge list (earned dates from the data), PR events stored on the way."""
    today = athlete.local_today
    runs = list(Activity.objects.filter(athlete=athlete, sport__icontains="run")
                .values_list("local_date", "total_distance_m"))
    run_dates = sorted({d for d, _ in runs})
    nights = dict(DailyMetrics.objects.filter(athlete=athlete, sleep_seconds__isnull=False,
                                              metric_date__lte=today)
                  .values_list("metric_date", "sleep_seconds"))
    for key, label, day in _pr_events(athlete):
        _store(athlete, key, Achievement.Kind.PR, label, day)
    pr_dates = list(Achievement.objects.filter(athlete=athlete, kind=Achievement.Kind.PR)
                    .values_list("earned_on", flat=True))
    from .illness import illness_days

    neutral = illness_days(athlete)          # R17: being ill never breaks a streak
    results = {
        "consistency": maths.consistent_weeks(run_dates, today, neutral),
        "distance": maths.first_5k([(d, m or 0) for d, m in runs]),
        "records": maths.records(pr_dates),
        "run_streak": maths.run_streak(run_dates, today, neutral),
        "sleep": maths.sleep_streak(nights),
    }
    smoke = _smoke(athlete)
    if smoke is not None:
        results["smoke_free"] = smoke
    cravings = _cravings(athlete)
    if cravings is not None:
        results["cravings"] = cravings
    recovery = _recovery(athlete)
    if recovery is not None:
        results["recovery"] = recovery
    return maths.badges(results)


def _recovery(athlete):
    """R17 §1: shown once the athlete has done one routine."""
    from analysis.recovery_routine import recovery_streak, streak_reached
    from apps.activities.recovery import _run_flags
    from apps.activities.models import RecoveryLog

    if not RecoveryLog.objects.filter(athlete=athlete).exists():
        return None
    flags = _run_flags(athlete)
    targets = [t for t, _, _ in maths.CATALOGUE["recovery"][1]]
    reached = streak_reached([(day, done) for day, done, _ in flags], targets)
    current, _ = recovery_streak([done for _, done, _ in flags])
    return reached, current


def _cravings(athlete):
    """R13 §8: resisted cravings, only once the athlete logs cravings at all."""
    from analysis.cravings import resisted_milestones
    from apps.habits.models import CravingLog

    rows = list(CravingLog.objects.filter(athlete=athlete).values_list("local_date", "smoked"))
    if not rows:
        return None
    return resisted_milestones([day for day, smoked in rows if not smoked])


def _store(athlete, key, kind, label, day) -> bool:
    if Achievement.objects.filter(athlete=athlete, key=key).exists():
        return False
    try:
        with transaction.atomic():
            old = (athlete.local_today - day).days > QUIET_AFTER_DAYS
            Achievement.objects.create(athlete=athlete, key=key, kind=kind, label=label,
                                       earned_on=day, seen_at=timezone.now() if old else None)
        return True
    except IntegrityError:          # a concurrent award got there first
        return False


def award(athlete) -> list[dict]:
    """Store every badge reached and not yet stored. Idempotent; returns the badges."""
    badges = evaluate(athlete)
    for badge in badges:
        if badge["earned_on"] is not None:
            _store(athlete, badge["key"], Achievement.Kind.BADGE, badge["label"],
                   badge["earned_on"])
    return badges


def payload(athlete) -> dict:
    badges = award(athlete)
    stored = {a.key: a for a in Achievement.objects.filter(athlete=athlete)}
    out = []
    for badge in badges:
        row = stored.get(badge["key"])
        earned = row is not None
        out.append({**badge, "earned": earned,
                    "earned_on": row.earned_on if earned else None,
                    "progress": ({"current": badge["target"], "target": badge["target"]}
                                 if earned else badge["progress"]),
                    "new": earned and row.seen_at is None})
    recent = sorted(stored.values(), key=lambda a: (a.earned_on, a.pk), reverse=True)[:RECENT]
    return {"badges": out,
            "recent": [{"key": a.key, "kind": a.kind, "label": a.label,
                        "earned_on": a.earned_on} for a in recent],
            "unseen": sum(1 for a in stored.values() if a.seen_at is None)}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def achievements(request):
    return Response(payload(request.user.athlete))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def achievements_seen(request):
    updated = Achievement.objects.filter(athlete=request.user.athlete,
                                         seen_at__isnull=True).update(seen_at=timezone.now())
    return Response({"updated": updated})
