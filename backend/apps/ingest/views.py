"""Garmin connect / disconnect / sync endpoints."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.coaching.throttles import FixedScopeThrottle

from apps.athletes.mixins import AthleteScopedMixin
from rest_framework import generics

from .garmin import GarminAuthError, GarminRateLimited, check_connection, sync_athlete
from .models import DailyMetrics
from .serializers import DailyMetricsSerializer
from .garmin_connect import MFARequired, connect, disconnect

logger = logging.getLogger(__name__)


class GarminThrottle(FixedScopeThrottle):
    scope = "garmin"


class GarminConnectThrottle(FixedScopeThrottle):
    """Per client IP, not per user: each attempt is a real Garmin login, and one
    person cycling through accounts should not get a fresh bucket per account."""

    scope = "garmin_connect"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def garmin_status(request):
    """Re-probes rather than trusting the stored flag — a token can look present and
    no longer work, and reporting a stale 'connected' is worse than reporting nothing."""
    return Response(check_connection(request.user.athlete))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([GarminConnectThrottle])
def garmin_connect_view(request):
    email = (request.data.get("email") or "").strip()
    password = request.data.get("password") or ""
    if not email or not password:
        return Response(
            {"detail": "Garmin email and password are both required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # The password is passed straight through and never stored, logged or echoed.
        return Response(connect(request.user.athlete, email, password))
    except MFARequired as exc:
        return Response({"detail": str(exc), "mfa": True}, status=status.HTTP_400_BAD_REQUEST)
    except GarminRateLimited as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    except GarminAuthError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    finally:
        del password


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def garmin_disconnect_view(request):
    return Response(disconnect(request.user.athlete))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([GarminThrottle])
def garmin_sync_view(request):
    from .sync_status import AlreadyRunning, auto_skip_reason, status_json, sync_lock

    athlete = request.user.athlete
    data = request.data if isinstance(request.data, dict) else {}
    try:
        limit = min(int(data.get("limit", 20)), 50)
    except (TypeError, ValueError):
        limit = 20
    # R16 §C: the app's auto-sync. Never calls Garmin when it shouldn't; always 200.
    auto = data.get("auto") is True or str(data.get("auto")).lower() in ("1", "true")
    if auto:
        reason = auto_skip_reason(athlete)
        if reason:
            return Response({"skipped": reason, "status": status_json(athlete)})

    try:
        with sync_lock(athlete):
            result = sync_athlete(athlete, limit=limit).as_dict()
        if not any("rate-limited" in e for e in result.get("errors", [])):
            from .tasks import queue_slow

            queue_slow(athlete)          # R10 §B: on the garmin queue
        athlete.refresh_from_db(fields=["garmin_last_sync", "garmin_connected"])
        return Response({**result, "status": status_json(athlete)})
    except AlreadyRunning as exc:
        if auto:
            return Response({"skipped": "running", "status": status_json(athlete)})
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except GarminRateLimited as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    except GarminAuthError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sync_status_view(request):
    """R16 §C: GET /sync/status/ — cheap (no Garmin call)."""
    from .sync_status import status_json

    return Response(status_json(request.user.athlete))


class DailyMetricsList(AthleteScopedMixin, generics.ListAPIView):
    """Wellness history, newest first. `?days=N` limits the window."""

    serializer_class = DailyMetricsSerializer
    permission_classes = [IsAuthenticated]
    queryset = DailyMetrics.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        try:
            days = min(int(self.request.query_params.get("days", 28)), 365)
        except (TypeError, ValueError):
            days = 28
        return queryset[:days]
