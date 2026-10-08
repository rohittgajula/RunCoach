"""Persisted plans, the day-by-day calendar and single workouts (spec §5).

Every query here filters on the requesting athlete — through AthleteScopedMixin for
the generic views, explicitly for the function views. A lookup by id that skipped
that filter would hand one athlete another's plan with a 200.
"""

from __future__ import annotations

import datetime as dt

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activities.models import Activity
from apps.athletes.mixins import AthleteScopedMixin
from apps.coaching.throttles import ChatThrottle, ChatWriteThrottle

from .models import INACTIVE_STATUSES, PlannedWorkout, TrainingPlan
from .plan_store import PlanError, accept_plan, decline_plan, rebuild_active_plan
from .presenters import activity_cards, guard_base, plan_detail, plan_summary, workout_json

MAX_CALENDAR_DAYS = 62
# Kinds after which the next empty day is labelled "Recovery day" rather than "Rest".
RECOVERY_AFTER = {"LONG", "INTERVALS", "TEMPO", "RACE"}
LONG_ACTIVITY_S = 75 * 60

# Workouts from these plans never reach the calendar: a proposal is not a commitment,
# and a declined one never was.
HIDDEN_PLAN_STATUSES = [TrainingPlan.Status.PROPOSED, TrainingPlan.Status.DECLINED]


def _plans(request):
    return TrainingPlan.objects.filter(athlete=request.user.athlete).select_related("race")


class PlanList(AthleteScopedMixin, generics.ListAPIView):
    """GET /plans/?status= -> [PlanSummary]"""

    permission_classes = [IsAuthenticated]
    queryset = TrainingPlan.objects.select_related("race").prefetch_related("phases")
    pagination_class = None

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        if wanted := request.query_params.get("status"):
            queryset = queryset.filter(status__in=wanted.split(","))
        today = request.user.athlete.local_today
        return Response([plan_summary(p, today) for p in queryset])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def active_plan(request):
    plan = _plans(request).filter(status=TrainingPlan.Status.ACTIVE).first()
    if plan is None:
        return Response({"detail": "No active plan."}, status=status.HTTP_404_NOT_FOUND)
    return Response(plan_detail(plan, request.user.athlete.local_today))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def plan_view(request, pk: int):
    plan = _plans(request).filter(pk=pk).first()
    if plan is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(plan_detail(plan, request.user.athlete.local_today))


def _transition(request, pk: int, action):
    plan = _plans(request).filter(pk=pk).first()
    if plan is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    try:
        plan = action(plan)
    except PlanError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    plan.refresh_from_db()
    return Response(plan_detail(plan, request.user.athlete.local_today))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plan_accept(request, pk: int):
    return _transition(request, pk, accept_plan)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plan_decline(request, pk: int):
    return _transition(request, pk, decline_plan)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plan_rebuild(request):
    """Rebuild the active plan from the current profile (e.g. new training days)."""
    athlete = request.user.athlete
    try:
        plan = rebuild_active_plan(athlete)
    except PlanError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    plan.refresh_from_db()
    return Response(plan_detail(plan, athlete.local_today))


def _parse_date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def calendar_days(request):
    """GET /calendar/?start=&end= (inclusive, at most 62 days).

    Defaults to a week back and two forward from the athlete's own today.
    """
    athlete = request.user.athlete
    today = athlete.local_today
    params = request.query_params
    start = _parse_date(params.get("start"))
    end = _parse_date(params.get("end"))
    if (params.get("start") and start is None) or (params.get("end") and end is None):
        return Response({"detail": "Dates must be YYYY-MM-DD."}, status=400)
    start = start or today - dt.timedelta(days=7)
    end = end or max(start, today) + dt.timedelta(days=14)
    if end < start:
        return Response({"detail": "end must not be before start."}, status=400)
    if (end - start).days + 1 > MAX_CALENDAR_DAYS:
        return Response(
            {"detail": f"At most {MAX_CALENDAR_DAYS} days per request."}, status=400
        )

    # Query whole Monday-Sunday weeks (and the day before start, for the recovery
    # label) so the week totals are right even when the range cuts a week in half.
    query_start = min(start - dt.timedelta(days=1), start - dt.timedelta(days=start.weekday()))
    query_end = end + dt.timedelta(days=6 - end.weekday())

    workouts = list(
        PlannedWorkout.objects.filter(
            athlete=athlete, date__gte=query_start, date__lte=query_end
        ).exclude(plan__status__in=HIDDEN_PLAN_STATUSES)
        .select_related("phase", "completed_activity__metrics")
        .prefetch_related("completed_activity__segments")
    )
    activities = list(
        Activity.objects.filter(
            athlete=athlete, local_date__gte=query_start, local_date__lte=query_end
        ).select_related("metrics").prefetch_related("segments").order_by("started_at")
    )

    in_range = [a for a in activities if start <= a.local_date <= end]
    cards = dict(zip((a.pk for a in in_range), activity_cards(athlete, in_range)))

    by_day_workouts: dict[dt.date, list] = {}
    for workout in workouts:
        by_day_workouts.setdefault(workout.date, []).append(workout)
    by_day_activities: dict[dt.date, list] = {}
    for activity in activities:
        by_day_activities.setdefault(activity.local_date, []).append(activity)

    def demanding(day: dt.date) -> bool:
        if any(
            w.kind in RECOVERY_AFTER and w.status not in INACTIVE_STATUSES
            for w in by_day_workouts.get(day, [])
        ):
            return True
        return any(
            (a.total_timer_s or 0) >= LONG_ACTIVITY_S for a in by_day_activities.get(day, [])
        )

    guard_inputs = guard_base(athlete) if workouts else None
    # R13 §4: strength sessions are calendar items of their own.
    from .strength_service import can_send, sessions_between, strength_json

    send = can_send(athlete)
    by_day_strength: dict[dt.date, list] = {}
    for session in sessions_between(athlete, start, end):
        by_day_strength.setdefault(session.date, []).append(strength_json(session, send))
    days = []
    cursor = start
    while cursor <= end:
        items = [
            {"type": "activity", "activity": cards[a.pk], "unplanned": cards[a.pk]["unplanned"]}
            for a in by_day_activities.get(cursor, []) if a.pk in cards
        ] + [
            {"type": "workout", "workout": workout_json(w, guard_inputs)}
            for w in by_day_workouts.get(cursor, [])
        ] + [
            {"type": "strength", "strength": s} for s in by_day_strength.get(cursor, [])
        ]
        rest = None
        if not items:
            rest = "Recovery day" if demanding(cursor - dt.timedelta(days=1)) else "Rest"
        days.append({"date": cursor, "items": items, "rest": rest})
        cursor += dt.timedelta(days=1)

    weeks = []
    week_start = start - dt.timedelta(days=start.weekday())
    while week_start <= end:
        week_end = week_start + dt.timedelta(days=6)
        week_workouts = [w for w in workouts if week_start <= w.date <= week_end
                         and w.status not in INACTIVE_STATUSES]
        week_activities = [a for a in activities if week_start <= a.local_date <= week_end]
        weeks.append({
            "start": week_start,
            "end": week_end,
            "planned_s": sum(w.duration_s for w in week_workouts),
            "planned_load": round(sum(w.load for w in week_workouts), 1),
            "actual_s": round(sum(a.total_timer_s or 0 for a in week_activities)),
            "actual_load": round(sum(
                (getattr(a, "metrics", None) and a.metrics.custom_load) or 0
                for a in week_activities
            ), 1),
        })
        week_start += dt.timedelta(days=7)

    return Response({"today": today, "days": days, "weeks": weeks})


def _workout(request, pk: int) -> PlannedWorkout | None:
    return (
        PlannedWorkout.objects.filter(athlete=request.user.athlete, pk=pk)
        .select_related("phase").first()
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def workout_view(request, pk: int):
    workout = _workout(request, pk)
    if workout is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        from apps.ingest.weather_services import workout_weather

        body = workout_json(workout)
        body["weather"] = workout_weather(request.user.athlete, workout)
        return Response(body)

    fields = []
    if "date" in request.data:
        new_date = _parse_date(request.data.get("date"))
        if new_date is None:
            return Response({"detail": "date must be YYYY-MM-DD."}, status=400)
        if new_date < request.user.athlete.local_today:
            return Response({"detail": "A workout cannot be moved into the past."}, status=400)
        if new_date != workout.date:
            # moved_from keeps the ORIGINAL date across several moves: that is the
            # one the plan intended.
            workout.moved_from = workout.moved_from or workout.date
            workout.date = new_date
            fields += ["date", "moved_from"]
    if "status" in request.data:
        new_status = request.data.get("status")
        settable = [s for s in PlannedWorkout.Status.values if s != "paused"]
        if new_status not in settable:
            # R17: "paused" belongs to illness mode (POST /illness/), not to PATCH.
            return Response(
                {"detail": f"status must be one of {', '.join(settable)}."},
                status=400,
            )
        workout.status = new_status
        if new_status != PlannedWorkout.Status.COMPLETED:
            workout.completed_activity = None
            fields.append("completed_activity")
        fields.append("status")
    if fields:
        from django.db import transaction

        from .garmin_sync import remove_from_garmin, resync_on_garmin

        with transaction.atomic():
            workout.save(update_fields=fields)
            # The watch copy follows: skipped -> off the watch; moved -> re-sent.
            if workout.status == PlannedWorkout.Status.SKIPPED:
                remove_from_garmin(workout.athlete, [workout.pk])
            elif "date" in fields:
                resync_on_garmin(workout.athlete, [workout.pk])
    return Response(workout_json(workout))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def workout_guide(request, pk: int):
    """Creates a thread with the workout attached and asks how to execute it."""
    from apps.coaching.chat import start_thread_with

    workout = _workout(request, pk)
    if workout is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    thread = start_thread_with(
        request.user.athlete,
        title=f"Guide: {workout.title}"[:120],
        content="How do I execute this workout?",
        attachments=[{"type": "workout", "id": workout.pk}],
    )
    return Response({"thread_id": thread.pk}, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatWriteThrottle])
def activity_review(request, pk: int):
    """GET: the R13 §7 post-run coach review. POST: open a chat thread reviewing it."""
    from apps.coaching.chat import start_thread_with

    activity = Activity.objects.filter(athlete=request.user.athlete, pk=pk) \
        .select_related("metrics").first()
    if activity is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        from apps.activities.reviews import review_json

        return Response(review_json(activity))
    thread = start_thread_with(
        request.user.athlete,
        title=f"Review: {activity.local_date:%a %-d %b} {activity.sport}"[:120],
        content="Review this activity",
        attachments=[{"type": "activity", "id": activity.pk}],
    )
    return Response({"thread_id": thread.pk}, status=status.HTTP_201_CREATED)


def _review_response(call):
    """503 {detail} whenever the model cannot be used (no key, budget, outage)."""
    from apps.coaching.client import AIUnavailable

    try:
        call()
    except AIUnavailable as exc:
        return Response({"detail": str(exc) or "The coach is unavailable right now."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def workout_review(request, pk: int):
    """R6 §3: generate (or fetch the cached) AI review of a completed workout."""
    from apps.coaching.services import review_activity

    workout = _workout(request, pk)
    if workout is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    activity = workout.completed_activity
    if activity is None:
        return Response({"detail": "This workout has no linked activity to review yet."},
                        status=status.HTTP_409_CONFLICT)
    failed = _review_response(lambda: review_activity(request.user.athlete, activity, workout))
    return failed or Response(workout_json(workout))


def activity_detail_json(athlete, activity: Activity) -> dict:
    """GET /activities/{id}/: the stored detail, plus the ActivityCard keys, `actual`,
    `review`, and — when the run completed a planned workout — `workout_id` and
    `compliance` (R6 §3)."""
    from apps.activities.serializers import ActivityDetailSerializer

    from .actuals import actual_json, compliance_json, review_json
    from .presenters import activity_card

    workout = PlannedWorkout.objects.filter(athlete=athlete, completed_activity=activity).first()
    return {
        **ActivityDetailSerializer(activity).data,
        **activity_card(athlete, activity),
        "actual": actual_json(activity),
        "review": review_json(activity),
        "workout_id": workout.pk if workout else None,
        "compliance": compliance_json(workout, activity) if workout else None,
        "checkin": _checkin_json(activity),
        "quality": _quality_json(activity),          # R17 §2
    }


def _quality_json(activity: Activity) -> dict | None:
    from apps.activities.quality import quality_json

    return quality_json(activity)


def _checkin_json(activity: Activity) -> dict | None:
    """R7 §2: the post-run check-in (a JournalEntry), or null."""
    from apps.journal.checkin import existing
    from apps.journal.serializers import JournalEntrySerializer

    entry = existing(activity)
    return JournalEntrySerializer(entry).data if entry else None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def activity_ai_review(request, pk: int):
    """R6 §3 for runs that are not linked to a workout (works for linked ones too)."""
    from apps.coaching.services import review_activity

    athlete = request.user.athlete
    activity = Activity.objects.filter(athlete=athlete, pk=pk).first()
    if activity is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    workout = PlannedWorkout.objects.filter(athlete=athlete, completed_activity=activity).first()
    failed = _review_response(lambda: review_activity(athlete, activity, workout))
    return failed or Response(activity_detail_json(athlete, activity))
