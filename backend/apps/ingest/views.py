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


class GarminSyncThrottle(GarminThrottle):
    """R18: auto POSTs are limited by the server-side guard (30 min, 5 min run-aware),
    not by the 10/hour bucket — a run-aware poll would otherwise use it up."""

    def allow_request(self, request, view):
        data = request.data if isinstance(request.data, dict) else {}
        if data.get("auto") is True or str(data.get("auto")).lower() in ("1", "true"):
            return True
        return super().allow_request(request, view)


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
@throttle_classes([GarminSyncThrottle])
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
    full = data.get("full") is True or str(data.get("full")).lower() in ("1", "true")
    if auto:
        reason = auto_skip_reason(athlete)
        if reason:
            return Response({"skipped": reason, "status": status_json(athlete)})
        # R18 §A: the same job path as a full refresh, throttled (and run-aware).
        from .sync_jobs import start
        from .sync_status import auto_mode

        mode = auto_mode(athlete)
        job, deduped = start(athlete, "run_check" if mode == "run_check" else "auto")
        return Response({"job_id": job.get("id"), "deduped": deduped, "mode": mode,
                         "status": status_json(athlete)})
    if full:
        return _full_sync(athlete)

    try:
        with sync_lock(athlete):
            result = sync_athlete(athlete, limit=limit).as_dict()
        if not any("rate-limited" in e for e in result.get("errors", [])):
            from .tasks import queue_intraday, queue_slow

            queue_slow(athlete)          # R10 §B: on the garmin queue
            # R18 root cause 1: intraday used to refresh only after the scheduled morning
            # sync — every sync now refreshes today + yesterday.
            queue_intraday(athlete)
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


def _full_sync(athlete):
    """R18 §A: POST /garmin/sync/ {full: true} → 202 {job_id, deduped, mode, status}."""
    from .sync_jobs import active_job_id, start
    from .sync_status import is_running, status_json
    from .tasks import garmin_blocked

    if not athlete.garmin_connected:
        return Response({"detail": "Connect your Garmin account first."},
                        status=status.HTTP_400_BAD_REQUEST)
    if garmin_blocked():
        return Response({"detail": "Garmin is rate-limiting this server — try again later.",
                         "status": status_json(athlete)},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    if is_running(athlete) and not active_job_id(athlete.pk):
        return Response({"detail": "A sync is already running."}, status=status.HTTP_409_CONFLICT)
    job, deduped = start(athlete, "full")
    return Response({"job_id": job.get("id"), "deduped": deduped, "mode": "full",
                     "status": status_json(athlete)}, status=status.HTTP_202_ACCEPTED)


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
