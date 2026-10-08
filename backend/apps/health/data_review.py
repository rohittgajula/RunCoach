"""R17: "Review these days/runs?" — the one place suggestions wait for a decision.

Rohit's rule: nothing is excluded or removed automatically. Runs the data-quality filter
scores low, days inside an illness period and activities Garmin no longer lists all
become items here; only the athlete's decision changes anything, and every decision can
be reset (null).
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import DayDataDecision, Illness

WINDOW_DAYS = 180
MAX_ITEMS = 200
DAY_DECISIONS = ("include", "exclude")


class ReviewError(ValueError):
    pass


def excluded_days(athlete) -> set[dt.date]:
    """Days the athlete explicitly left out of wellness trends."""
    return set(DayDataDecision.objects.filter(athlete=athlete, decision="exclude")
               .values_list("date", flat=True))


def day_flag(athlete, day: dt.date) -> dict | None:
    from .illness import illness_on

    ill = illness_on(athlete, day)
    if ill is None:
        return None
    from planning.illness import label_for

    row = DayDataDecision.objects.filter(athlete=athlete, date=day).first()
    return {"reason": "illness", "illness_id": ill.pk,
            "text": f"You were unwell ({label_for(ill.type).lower()}) — resting HR, HRV "
                    f"and sleep may look off.",
            "decision": row.decision if row else None}


def flagged_days(athlete, start: dt.date, end: dt.date) -> list[dict]:
    from .illness import periods

    excluded = excluded_days(athlete)
    out = []
    for s, e, _ in periods(athlete):
        day = max(s, start)
        while day <= min(e, end):
            out.append({"date": day, "reason": "illness", "excluded": day in excluded})
            day += dt.timedelta(days=1)
    return sorted(out, key=lambda d: d["date"])


# --- items ----------------------------------------------------------------------------

def _run_item(q) -> dict:
    from apps.activities.quality import quality_json

    a = q.activity
    body = quality_json(a)
    reason = body["suggestion_reason"]
    if body["suggestion"] and not q.decision:
        text = (f"{reason} on {a.local_date.strftime('%a %-d %b')}'s run — leave it out of "
                f"trends?")
    elif body["use_suggestion"] and not q.use_choice:
        text = (f"{a.local_date.strftime('%a %-d %b')}'s run has sensor glitches — use the "
                f"fixed copy for its numbers?")
    else:
        text = f"{a.local_date.strftime('%a %-d %b')}'s run: {body['chip']}."
    return {"kind": "run", "id": a.pk, "date": a.local_date,
            "title": f"{a.sport.replace('_', ' ').title()} · "
                     f"{(a.total_distance_m or 0) / 1000:.1f} km",
            "score": q.score, "suggestion": body["suggestion"],
            "suggestion_reason": reason, "use_suggestion": body["use_suggestion"],
            "decision": q.decision or None, "use_choice": q.use_choice or None,
            "pending": body["pending_review"], "text": text}


def _illness_item(athlete, ill: Illness, decisions: dict, data_days: set) -> dict:
    from planning.illness import label_for

    end = ill.recovered_on or athlete.local_today
    days = []
    day = ill.start_date
    while day <= end:
        days.append({"date": day, "decision": decisions.get(day), "has_data": day in data_days})
        day += dt.timedelta(days=1)
    values = {d["decision"] for d in days}
    decision = values.pop() if len(values) == 1 else "mixed"
    pending = any(d["decision"] is None for d in days)
    span = (f"{ill.start_date.strftime('%-d %b')}–{end.strftime('%-d %b')}"
            if end != ill.start_date else ill.start_date.strftime("%-d %b"))
    return {"kind": "illness", "id": ill.pk, "type": ill.type,
            "label": label_for(ill.type), "start": ill.start_date, "end": end,
            "days": days, "decision": decision, "pending": pending,
            "text": f"You were unwell {span} — resting HR and HRV may look off. Leave those "
                    f"days out of trends?"}


def _garmin_item(check) -> dict:
    a = check.activity
    return {"kind": "deleted_in_garmin", "id": a.pk, "date": a.local_date,
            "title": f"{a.sport.replace('_', ' ').title()} · "
                     f"{(a.total_distance_m or 0) / 1000:.1f} km",
            "detected_at": check.detected_at, "decision": check.decision or None,
            "pending": not check.decision,
            "text": f"This activity from {a.local_date.strftime('%a %-d %b')} is no longer "
                    f"in Garmin Connect — remove it here too?"}


def items(athlete, include_decided: bool = False) -> list[dict]:
    from apps.activities.models import ActivityQuality, GarminDeletionCheck
    from apps.ingest.models import DailyMetrics

    since = athlete.local_today - dt.timedelta(days=WINDOW_DAYS)
    out: list[dict] = []
    qs = (ActivityQuality.objects.filter(activity__athlete=athlete,
                                         activity__local_date__gte=since)
          .select_related("activity"))
    for q in qs:
        s = q.summary or {}
        relevant = s.get("suggestion") or s.get("use_suggestion") or q.decision or q.use_choice
        if not relevant:
            continue
        item = _run_item(q)
        if item["pending"] or include_decided:
            out.append(item)
    illnesses = list(Illness.objects.filter(athlete=athlete).exclude(
        recovered_on__lt=since))
    if illnesses:
        decisions = dict(DayDataDecision.objects.filter(athlete=athlete)
                         .values_list("date", "decision"))
        data_days = set(DailyMetrics.objects.filter(
            athlete=athlete, metric_date__gte=min(i.start_date for i in illnesses))
            .values_list("metric_date", flat=True))
        for ill in illnesses:
            item = _illness_item(athlete, ill, decisions, data_days)
            if item["pending"] or include_decided:
                out.append(item)
    for check in (GarminDeletionCheck.objects.filter(athlete=athlete)
                  .select_related("activity")):
        item = _garmin_item(check)
        if item["pending"] or include_decided:
            out.append(item)
    out.sort(key=lambda i: (i.get("date") or i.get("end")), reverse=True)
    return out


def payload(athlete, include_decided: bool = False) -> dict:
    rows = items(athlete, include_decided)
    return {"pending": sum(1 for r in rows if r["pending"]), "items": rows}


# --- decisions ------------------------------------------------------------------------

def _date(value) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ReviewError("date must be YYYY-MM-DD.") from None


def _validate(athlete, raw) -> list[tuple]:
    from apps.activities.models import Activity, GarminDeletionCheck

    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ITEMS:
        raise ReviewError(f"items must be a list of 1–{MAX_ITEMS} decisions.")
    plan = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ReviewError("Each item must be an object.")
        kind = entry.get("kind")
        if kind == "run":
            activity = Activity.objects.filter(athlete=athlete, pk=entry.get("id")).first()
            if activity is None:
                raise ReviewError(f"Unknown run id {entry.get('id')}.")
            changes = {}
            if "decision" in entry:
                if entry["decision"] not in (None, *DAY_DECISIONS):
                    raise ReviewError("decision must be include, exclude or null.")
                changes["decision"] = entry["decision"]
            if "use" in entry:
                if entry["use"] not in (None, "cleaned", "raw"):
                    raise ReviewError("use must be cleaned, raw or null.")
                changes["use"] = entry["use"]
            if not changes:
                raise ReviewError("A run decision needs decision and/or use.")
            plan.append(("run", activity, changes))
        elif kind == "day":
            if entry.get("decision", "missing") not in (None, *DAY_DECISIONS):
                raise ReviewError("decision must be include, exclude or null.")
            day = _date(entry.get("date"))
            if day > athlete.local_today:
                raise ReviewError("date can't be in the future.")
            plan.append(("day", day, entry["decision"]))
        elif kind == "illness":
            ill = Illness.objects.filter(athlete=athlete, pk=entry.get("id")).first()
            if ill is None:
                raise ReviewError(f"Unknown illness id {entry.get('id')}.")
            if entry.get("decision", "missing") not in (None, *DAY_DECISIONS):
                raise ReviewError("decision must be include, exclude or null.")
            plan.append(("illness", ill, entry["decision"]))
        elif kind == "deleted_in_garmin":
            check = (GarminDeletionCheck.objects.filter(athlete=athlete,
                                                        activity_id=entry.get("id"))
                     .select_related("activity").first())
            if check is None:
                raise ReviewError(f"No Garmin question for activity {entry.get('id')}.")
            if entry.get("decision") not in ("remove", "keep"):
                raise ReviewError("decision must be remove or keep.")
            plan.append(("deleted_in_garmin", check, entry["decision"]))
        else:
            raise ReviewError("kind must be run, day, illness or deleted_in_garmin.")
    return plan


def _set_day(athlete, day: dt.date, decision) -> None:
    if decision is None:
        DayDataDecision.objects.filter(athlete=athlete, date=day).delete()
    else:
        DayDataDecision.objects.update_or_create(athlete=athlete, date=day,
                                                 defaults={"decision": decision})


def decide(athlete, raw) -> dict:
    from apps.activities.deletion import delete_activity
    from apps.activities.models import ActivityTombstone
    from apps.activities.quality import BadChoice, set_choices

    plan = _validate(athlete, raw)
    touched: list[tuple[str, object]] = []
    with transaction.atomic():
        for kind, target, value in plan:
            if kind == "run":
                try:
                    set_choices(target, **value)
                except BadChoice as exc:
                    raise ReviewError(str(exc)) from None
                touched.append(("run", target.pk))
            elif kind == "day":
                _set_day(athlete, target, value)
                touched.append(("day", target))
            elif kind == "illness":
                end = target.recovered_on or athlete.local_today
                day = target.start_date
                while day <= end:
                    _set_day(athlete, day, value)
                    day += dt.timedelta(days=1)
                touched.append(("illness", target.pk))
            else:
                if value == "remove":
                    delete_activity(target.activity, reason=ActivityTombstone.Reason.GARMIN)
                    touched.append(("removed", target.activity_id))
                else:
                    target.decision = "keep"
                    target.decided_at = timezone.now()
                    target.save(update_fields=["decision", "decided_at"])
                    touched.append(("deleted_in_garmin", target.activity_id))
    every = items(athlete, include_decided=True)
    wanted = []
    for kind, key in touched:
        for item in every:
            if kind == "day" and item["kind"] == "illness" and any(
                    d["date"] == key for d in item["days"]):
                wanted.append(item)
            elif item["kind"] == kind and item.get("id") == key:
                wanted.append(item)
    unique = []
    for item in wanted:
        if item not in unique:
            unique.append(item)
    return {"updated": len(plan), "items": unique}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def data_review(request):
    include = str(request.query_params.get("all", "0")).lower() in ("1", "true")
    return Response(payload(request.user.athlete, include))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def data_review_decide(request):
    data = request.data if isinstance(request.data, dict) else {}
    try:
        return Response(decide(request.user.athlete, data.get("items")))
    except ReviewError as exc:
        return Response({"detail": str(exc)}, status=400)
