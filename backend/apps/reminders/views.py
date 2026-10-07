"""R10 §C12 endpoints: settings, subscribe / unsubscribe and a test push."""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PushSubscription
from .push import available, send_to_athlete
from .nudges import NUDGES, nudges_json, quiet_json, validate_patch, validate_quiet
from .service import IOS_NOTE, REMINDERS, reminders_json, settings_for

UNAVAILABLE = "Reminders aren't set up on this server yet."


def _data_as_of(athlete):
    from apps.ingest.models import IntradayDay

    return (IntradayDay.objects.filter(athlete=athlete).order_by("-fetched_at")
            .values_list("fetched_at", flat=True).first())


def _state(athlete) -> dict:
    row = settings_for(athlete)
    return {"available": available(),
            "public_key": settings.VAPID_PUBLIC_KEY if available() else None,
            "subscriptions": PushSubscription.objects.filter(athlete=athlete).count(),
            "ios_note": IOS_NOTE,
            "reminders": reminders_json(row),
            # R11 §C
            "nudges": nudges_json(row),
            "quiet_hours": quiet_json(row),
            "data_as_of": _data_as_of(athlete)}


def _bad(message: str) -> Response:
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def reminders(request):
    athlete = request.user.athlete
    if request.method == "PATCH":
        row = settings_for(athlete)
        if not isinstance(request.data, dict):
            return _bad("Send an object keyed by reminder.")
        updates: dict = {}
        for key, change in request.data.items():
            if key in NUDGES or key == "quiet_hours":
                try:
                    updates.update(validate_quiet(change) if key == "quiet_hours"
                                   else validate_patch(key, change))
                except ValueError as exc:
                    return _bad(str(exc))
                continue
            if key not in REMINDERS:
                return _bad(f"Unknown reminder: {key}.")
            if not isinstance(change, dict) or not set(change) <= {"enabled", "time"}:
                return _bad(f"{key} takes {{enabled?, time?}}.")
            if "enabled" in change:
                if not isinstance(change["enabled"], bool):
                    return _bad(f"{key}.enabled must be true or false.")
                updates[key] = change["enabled"]
            if "time" in change:
                try:
                    updates[f"{key}_time"] = dt.datetime.strptime(str(change["time"]),
                                                                  "%H:%M").time()
                except ValueError:
                    return _bad(f"{key}.time must be HH:MM (24 h).")
        for field, value in updates.items():
            setattr(row, field, value)
        if updates:
            row.save()
    return Response(_state(athlete))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def subscribe(request):
    if not available():
        return Response({"detail": UNAVAILABLE}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    endpoint = request.data.get("endpoint")
    keys = request.data.get("keys") or {}
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") \
            or len(endpoint) > 1000:
        return _bad("endpoint must be the https URL from the browser's push subscription.")
    if not isinstance(keys, dict) or not keys.get("p256dh") or not keys.get("auth") \
            or len(str(keys["p256dh"])) > 200 or len(str(keys["auth"])) > 100:
        return _bad("keys.p256dh and keys.auth are required.")
    athlete = request.user.athlete
    existing = PushSubscription.objects.filter(endpoint=endpoint).first()
    if existing is not None and existing.athlete_id == athlete.pk:
        existing.p256dh, existing.auth = str(keys["p256dh"]), str(keys["auth"])
        existing.save(update_fields=["p256dh", "auth"])
        return Response({"id": existing.pk, "created": False})
    if existing is not None:
        # One browser, a different account signed in now: the browser follows the
        # account that is using it.
        existing.delete()
    sub = PushSubscription.objects.create(
        athlete=athlete, endpoint=endpoint, p256dh=str(keys["p256dh"]), auth=str(keys["auth"]),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300])
    return Response({"id": sub.pk, "created": True}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def unsubscribe(request):
    endpoint = request.data.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return _bad("endpoint is required.")
    deleted, _ = PushSubscription.objects.filter(athlete=request.user.athlete,
                                                 endpoint=endpoint).delete()
    return Response({"deleted": deleted})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def test_push(request):
    if not available():
        return Response({"detail": UNAVAILABLE}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    sent, failed = send_to_athlete(request.user.athlete, {
        "title": "RunCoach", "body": "Reminders are working.", "url": "/me", "tag": "test"})
    return Response({"sent": sent, "failed": failed})
